from flask import Flask, jsonify, request, render_template_string, send_from_directory
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import threading
import time
from datetime import datetime, timedelta
import os
import sys

app = Flask(__name__)
# Enhanced CORS configuration
cors_config = {
    "origins": [
        "http://localhost:*",
        "http://127.0.0.1:*",
        "https://my-player-vrse.onrender.com/",
        "https://*.vercel.app",
        "https://*.netlify.app",
        "https://gajju-trial2.pages.dev/",
        "file://",
    ],
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": [
        "Content-Type",
        "Authorization",
        "Access-Control-Allow-Credentials",
        "Access-Control-Allow-Origin",
        "Accept"
    ],
    "supports_credentials": True,
    "max_age": 3600
}

# Apply CORS with specific configuration
CORS(app, resources={
    r"/api/*": cors_config,
    r"/": cors_config,
    r"/live": cors_config
})

# Add after_request handler for additional CORS headers
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    
    # List of allowed origins
    allowed_origins = [
        'http://localhost:3000',
        'http://localhost:5000',
        'http://localhost:8080',
        'http://127.0.0.1:5000',
    ]
    
    # If origin is in allowed list or in development
    if origin in allowed_origins or (app.debug and origin and origin.startswith('http://localhost')):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept'
    
    return response

# Global variables
CURRENT_MATCH_URL = None
MATCH_DATA = {}
AUTO_UPDATE = True
UPDATE_INTERVAL = 15  # seconds

class Colors:
    """Terminal colors"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class CricketScraper:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
        
    def scrape_crex_scores(self, match_url):
        """Scrape live scores from CREX"""
        try:
            response = requests.get(match_url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title_elem = soup.find('title')
            title_text = title_elem.text.strip() if title_elem else ""
            
            data = self.parse_title_data(title_text)
            data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            return data
            
        except Exception as e:
            print(f"{Colors.FAIL}Error scraping: {str(e)}{Colors.ENDC}")
            return None

    def parse_title_data(self, title_text):
        """Parse the title text to extract match information and state"""
        data = {
            'matchState': 'UNKNOWN', 'title': title_text, 'shortTitle': '',
            'result': '', 'startTimeUTC': None, 'update': 'Live',
            'livescore': title_text.split(' | ')[0], 'runrate': 'CRR: 0.00',
            'team1_name': 'Team 1', 'team1_score': '0', 'team1_wickets': '0', 'team1_overs': '0.0',
            'team2_name': 'Team 2', 'team2_score': '0', 'team2_wickets': '0', 'team2_overs': '0.0',
            'team2_status': 'Yet to bat',
            'batterone': 'Batsman 1', 'batsmanonerun': '0', 'batsmanoneball': '(0)', 'batsmanonesr': '0.00',
            'battertwo': 'Batsman 2', 'batsmantworun': '0', 'batsmantwoball': '(0)', 'batsmantwosr': '0.00'
        }
        
        score_part = title_text.split(' | ')[0]

        if "won by" in score_part.lower() or "beat" in score_part.lower() or "match drawn" in score_part.lower():
            data['matchState'] = 'ENDED'
            data['result'] = score_part
            try:
                teams_part = title_text.split(' | ')[1]
                vs_match = re.search(r'(.+?)\s+vs\s+(.+?),', teams_part)
                if vs_match:
                    data['team1_name'], data['team2_name'] = vs_match.group(1).strip(), vs_match.group(2).strip()
                    data['shortTitle'] = f"{data['team1_name']} vs {data['team2_name']}"
            except Exception: pass
            return data

        if "starts at" in score_part.lower() or re.search(r'in\s+\d+', score_part.lower()):
            data['matchState'] = 'UPCOMING'
            try:
                teams_part = score_part.split(',')[0]
                vs_match = re.search(r'(.+?)\s+vs\s+(.+)', teams_part)
                if vs_match:
                    data['team1_name'], data['team2_name'] = vs_match.group(1).strip(), vs_match.group(2).strip()
                    data['shortTitle'] = f"{data['team1_name']} vs {data['team2_name']}"
                time_match = re.search(r'in\s+(?:(\d+)h\s*)?(?:(\d+)m)?', score_part)
                if time_match:
                    hours, minutes = int(time_match.group(1) or 0), int(time_match.group(2) or 0)
                    start_time = datetime.utcnow() + timedelta(hours=hours, minutes=minutes)
                    data['startTimeUTC'] = start_time.isoformat() + "Z"
            except Exception as e:
                print(f"Error parsing upcoming match time: {e}")
            return data
            
        data['matchState'] = 'LIVE'
        try:
            if ' vs ' in score_part:
                vs_index = score_part.find(' vs ')
                team1_full, team2_full = score_part[:vs_index].strip(), score_part[vs_index + 4:].strip()
                
                team1_name_match = re.match(r'^([^\d]+)', team1_full)
                if team1_name_match: data['team1_name'] = team1_name_match.group(1).strip()
                
                team2_name_match = re.match(r'^([^\d]+)', team2_full)
                if team2_name_match: data['team2_name'] = team2_name_match.group(1).strip()

                if team1_name_match and team2_name_match:
                    data['shortTitle'] = f"{data['team1_name']} vs {data['team2_name']}"

                score_match = re.search(r'(\d+)-(\d+)', team1_full)
                if score_match: data['team1_score'], data['team1_wickets'] = score_match.groups()
                
                overs_match = re.search(r'\((\d+\.\d+)\)', team1_full)
                if overs_match: data['team1_overs'] = overs_match.group(1)
                
                score_overs_match = re.search(r'\d+-\d+\s+\(\d+\.\d+\)', team1_full)
                if score_overs_match:
                    batsmen_part = team1_full[score_overs_match.end():].strip()
                    if batsmen_part.startswith('(') and batsmen_part.endswith(')'):
                        batsmen_str = batsmen_part[1:-1]
                        batsmen_list = [b.strip() for b in batsmen_str.split(',')]
                        for i, info in enumerate(batsmen_list[:2]):
                            bat_match = re.match(r'^(.+?)\s+(\d+)\((\d+)\)$', info.strip())
                            if bat_match:
                                name, runs, balls = bat_match.groups()
                                sr = f"{(int(runs) * 100 / int(balls)):.2f}" if int(balls) > 0 else "0.00"
                                if i == 0:
                                    data.update({'batterone': name.strip(), 'batsmanonerun': runs, 'batsmanoneball': f"({balls})", 'batsmanonesr': sr})
                                else:
                                    data.update({'battertwo': name.strip(), 'batsmantworun': runs, 'batsmantwoball': f"({balls})", 'batsmantwosr': sr})
                
                score_match_t2 = re.search(r'(\d+)-(\d+)', team2_full)
                if score_match_t2: data['team2_score'], data['team2_wickets'] = score_match_t2.groups()
                
                overs_match_t2 = re.search(r'\(\(?(\d+(?:\.\d+)?)\)?\)', team2_full)
                if overs_match_t2: data['team2_overs'] = overs_match_t2.group(1)
                
                if data['team2_score'] != '0':
                    data['team2_status'] = f"{data['team2_score']}-{data['team2_wickets']} ({data['team2_overs']} overs)"
                
                try:
                    t1_runs, t1_overs_dec = int(data['team1_score']), self.overs_to_decimal(data['team1_overs'])
                    if t1_overs_dec > 0:
                        data['runrate'] = f'CRR: {round(t1_runs / t1_overs_dec, 2)}'
                        t2_runs = int(data['team2_score'])
                        if t2_runs > 0:
                            target = t2_runs + 1
                            runs_needed = target - t1_runs
                            overs_left_dec = self.overs_to_decimal(data['team2_overs']) - t1_overs_dec
                            if overs_left_dec > 0 and runs_needed > 0:
                                data['runrate'] += f' | RRR: {round(runs_needed / overs_left_dec, 2)}'
                            data['update'] = f"Target: {target}"
                except (ValueError, ZeroDivisionError): pass
        except Exception as e:
            print(f"Error parsing live title: {str(e)}")
        return data
    
    def overs_to_decimal(self, overs):
        try:
            if '.' in overs:
                parts = overs.split('.')
                return int(parts[0]) + (int(parts[1]) / 6)
            return float(overs)
        except:
            return 0.0

URL_INPUT_PAGE = """
<!DOCTYPE html><html><head><title>Cricket Score Tracker - Control Panel</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',sans-serif;background:linear-gradient(135deg,#0f0c29 0%,#302b63 50%,#24243e 100%);color:white;min-height:100vh;padding:20px}.container{max-width:800px;margin:0 auto}.card{background:rgba(255,255,255,0.1);padding:30px;border-radius:20px;backdrop-filter:blur(10px);margin-bottom:20px;box-shadow:0 8px 32px 0 rgba(31,38,135,0.37)}h1{margin-bottom:30px;text-align:center;font-size:2.5rem}h2{margin-bottom:20px;color:#667eea}input{width:100%;padding:15px;font-size:16px;border:none;border-radius:10px;background:rgba(255,255,255,0.2);color:white;margin-bottom:20px}input::placeholder{color:rgba(255,255,255,0.7)}button{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border:none;padding:12px 30px;font-size:16px;border-radius:50px;cursor:pointer;transition:all .3s ease;margin-right:10px}button:hover{transform:translateY(-2px);box-shadow:0 5px 20px rgba(0,0,0,0.3)}.status{padding:15px;border-radius:10px;margin-top:20px}.success{background:rgba(46,204,113,0.2);color:#2ecc71}.error{background:rgba(231,76,60,0.2);color:#e74c3c}.info{background:rgba(52,152,219,0.2);color:#3498db}.current-match{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:20px}.stat-box{background:rgba(255,255,255,0.05);padding:20px;border-radius:10px;text-align:center}.stat-label{font-size:.9rem;opacity:.8;margin-bottom:5px}.stat-value{font-size:1.5rem;font-weight:bold;color:#ffd93d}.endpoints{background:rgba(255,255,255,0.05);padding:20px;border-radius:10px;margin-top:20px}.endpoint{padding:10px;margin:5px 0;background:rgba(255,255,255,0.05);border-radius:5px;font-family:monospace}.live-indicator{display:inline-block;width:10px;height:10px;background:#2ecc71;border-radius:50%;animation:pulse 2s infinite;margin-right:10px}@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(46,204,113,0.7)}70%{box-shadow:0 0 0 10px rgba(46,204,113,0)}100%{box-shadow:0 0 0 0 rgba(46,204,113,0)}}</style></head><body><div class=container><div class=card><h1>🏏 Cricket Score Tracker</h1><form onsubmit=setURL(event)><input type=url id=matchUrl placeholder=https://crex.com/scoreboard/... required value="{{ current_url or '' }}"><div><button type=submit>Start Tracking</button><button type=button onclick=refreshScores()>🔄 Refresh Now</button><button type=button onclick=toggleAutoUpdate()><span id=autoUpdateBtn>{{ '⏸️ Pause' if auto_update else '▶️ Resume' }} Auto-Update</span></button><button type=button onclick="window.location.href='/live'">📺 View Live Scores</button></div></form><div id=status></div></div>{% if current_url and match_data %}<div class=card><h2><span class=live-indicator></span>Current Match</h2><div class=current-match><div class=stat-box><div class=stat-label>{{ match_data.get('team1_name', 'Team 1') }}</div><div class=stat-value>{{ match_data.get('team1_score', '0') }}-{{ match_data.get('team1_wickets', '0') }}</div><div style=opacity:.8>({{ match_data.get('team1_overs', '0') }} overs)</div></div><div class=stat-box><div class=stat-label>{{ match_data.get('team2_name', 'Team 2') }}</div>{% if match_data.get('team2_status', 'Yet to bat') != 'Yet to bat' %}<div class=stat-value>{{ match_data.get('team2_score', '0') }}-{{ match_data.get('team2_wickets', '0') }}</div><div style=opacity:.8>({{ match_data.get('team2_overs', '0') }} overs)</div>{% else %}<div class=stat-value>Yet to bat</div>{% endif %}</div><div class=stat-box><div class=stat-label>Run Rate</div><div class=stat-value>{{ match_data.get('runrate', 'CRR: 0.00') }}</div></div><div class=stat-box><div class=stat-label>Last Update</div><div class=stat-value>{{ match_data.get('timestamp', 'N/A') }}</div></div></div>{% if match_data.get('batterone', 'Batsman 1') != 'Batsman 1' %}<div class=stat-box style=margin-top:20px><h3 style=margin-bottom:15px>Current Batsmen</h3><p>🏏 {{ match_data.get('batterone') }}: {{ match_data.get('batsmanonerun') }} {{ match_data.get('batsmanoneball') }} SR: {{ match_data.get('batsmanonesr') }}</p>{% if match_data.get('battertwo', 'Batsman 2') != 'Batsman 2' %}<p>🏏 {{ match_data.get('battertwo') }}: {{ match_data.get('batsmantworun') }} {{ match_data.get('batsmantwoball') }} SR: {{ match_data.get('batsmantwosr') }}</p>{% endif %}</div>{% endif %}</div>{% endif %}<div class=card><h2>API Endpoints</h2><div class=endpoints><div class=endpoint>GET /api/current-score - Get current match scores</div><div class=endpoint>GET /api/scrape?url={match_url} - Scrape specific match</div><div class=endpoint>POST /api/set-url - Set new match URL</div></div></div></div><script>let autoUpdate={{ 'true' if auto_update else 'false' }};async function setURL(e){e.preventDefault();const t=document.getElementById("matchUrl").value,s=document.getElementById("status");s.innerHTML="⏳ Setting up tracking...",s.className="status info";try{const e=await fetch("/api/set-url",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:t})}),a=await e.json();e.ok?(s.innerHTML="✅ Tracking started successfully!",s.className="status success",setTimeout(()=>window.location.reload(),1500)):(s.innerHTML="❌ "+(a.error||"Failed to set URL"),s.className="status error")}catch(e){s.innerHTML="❌ Error: "+e.message,s.className="status error"}}async function refreshScores(){const e=document.getElementById("status");e.innerHTML="🔄 Refreshing scores...",e.className="status info";try{const t=await fetch("/api/scrape");await t.json();t.ok?(e.innerHTML="✅ Scores refreshed!",e.className="status success",setTimeout(()=>window.location.reload(),1e3)):(e.innerHTML="❌ Failed to refresh scores",e.className="status error")}catch(t){e.innerHTML="❌ Error: "+t.message,e.className="status error"}}async function toggleAutoUpdate(){autoUpdate=!autoUpdate;const e=document.getElementById("autoUpdateBtn");e.textContent=autoUpdate?"⏸️ Pause Auto-Update":"▶️ Resume Auto-Update";try{await fetch("/api/toggle-auto-update",{method:"POST"})}catch(e){console.error("Failed to toggle auto-update:",e)}}autoUpdate&&setInterval(()=>{window.location.reload()},3e4)</script></body></html>
"""

scraper = CricketScraper()

@app.route('/')
def home():
    return render_template_string(URL_INPUT_PAGE, current_url=CURRENT_MATCH_URL, match_data=MATCH_DATA, auto_update=AUTO_UPDATE)

@app.route('/live')
def live_scores():
    if os.path.exists('index.html'):
        return send_from_directory('.', 'index.html')
    return "<h3>index.html not found!</h3>"

@app.route('/api/set-url', methods=['POST'])
def set_url():
    global CURRENT_MATCH_URL, MATCH_DATA
    url = request.json.get('url')
    if not url: return jsonify({"error": "URL is required"}), 400
    CURRENT_MATCH_URL = url
    scraped_data = scraper.scrape_crex_scores(url)
    if scraped_data:
        MATCH_DATA = scraped_data
        print_match_update(scraped_data)
        return jsonify({"message": "URL set successfully", "initial_data": scraped_data})
    return jsonify({"error": "Failed to scrape initial data"}), 500

@app.route('/api/current-score')
def get_current_score():
    headers = {'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache', 'Expires': '0'}
    if not CURRENT_MATCH_URL:
        return jsonify({"error": "No match URL set."}), 400, headers
    
    # Always fetch latest for this endpoint to ensure freshness
    data = scraper.scrape_crex_scores(CURRENT_MATCH_URL)
    if data:
        MATCH_DATA.update(data) # Update global state
        return jsonify(MATCH_DATA), 200, headers
    
    # Fallback to stored data if fetch fails
    if MATCH_DATA:
        return jsonify(MATCH_DATA), 200, headers
        
    return jsonify({"error": "No data available yet."}), 503, headers

@app.route('/api/scrape')
def scrape_match():
    global CURRENT_MATCH_URL, MATCH_DATA
    match_url = request.args.get('url') or CURRENT_MATCH_URL
    if not match_url: return jsonify({"error": "No match URL provided or set"}), 400
    data = scraper.scrape_crex_scores(match_url)
    if data:
        MATCH_DATA = data
        print_match_update(data)
        return jsonify(data)
    return jsonify({"error": "Unable to scrape match data"}), 500

def print_banner():
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗\n"
          f"║         {Colors.BOLD}🏏  CRICKET SCORE TRACKER - CREX SCRAPER  🏏{Colors.ENDC}{Colors.CYAN}         ║\n"
          f"╚═══════════════════════════════════════════════════════════╝{Colors.ENDC}")

def print_match_update(data):
    print(f"\n{Colors.GREEN}━━━ Match Update at {data.get('timestamp', '')} ━━━{Colors.ENDC}")
    print(f"{Colors.BOLD}Score:{Colors.ENDC} {data.get('livescore', 'N/A')}")
    if data.get('batterone', 'Batsman 1') != 'Batsman 1':
        print(f"\n{Colors.CYAN}At the Crease:{Colors.ENDC}")
        print(f"  • {data.get('batterone')}: {data.get('batsmanonerun')}{data.get('batsmanoneball')} SR: {data.get('batsmanonesr')}")
        if data.get('battertwo', 'Batsman 2') != 'Batsman 2':
            print(f"  • {data.get('battertwo')}: {data.get('batsmantworun')}{data.get('batsmantwoball')} SR: {data.get('batsmantwosr')}")
    print(f"{Colors.GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.ENDC}\n")

def auto_update_scores():
    while True:
        if AUTO_UPDATE and CURRENT_MATCH_URL:
            print(f"{Colors.CYAN}[Auto-Update] Fetching latest scores...{Colors.ENDC}")
            data = scraper.scrape_crex_scores(CURRENT_MATCH_URL)
            if data:
                MATCH_DATA = data
                print_match_update(data)
            else:
                print(f"{Colors.FAIL}[Auto-Update] Failed to fetch scores{Colors.ENDC}")
        time.sleep(UPDATE_INTERVAL)

def get_user_input():
    global CURRENT_MATCH_URL, MATCH_DATA
    print_banner()
    url = ""
    if len(sys.argv) > 1:
        url = sys.argv[1]
        print(f"\n{Colors.GREEN}✅ URL provided via command line.{Colors.ENDC}")
    else:
        url = input(f"\n{Colors.CYAN}Enter CREX match URL (or press Enter to set via web): {Colors.ENDC}").strip()
    
    if url:
        CURRENT_MATCH_URL = url
        print(f"{Colors.CYAN}📊 Fetching initial scores...{Colors.ENDC}")
        data = scraper.scrape_crex_scores(CURRENT_MATCH_URL)
        if data: MATCH_DATA = data; print_match_update(data)
    else:
        print(f"\n{Colors.CYAN}📌 No URL provided. Set it via the web interface.{Colors.ENDC}")
    print_server_info()

def print_server_info():
    print(f"\n{Colors.GREEN}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}🌐 Server is live at: http://localhost:5000{Colors.ENDC}")
    print(f"  • View scoreboard at: {Colors.CYAN}http://localhost:5000/live{Colors.ENDC}")
    if CURRENT_MATCH_URL: print(f"  • Tracking: {Colors.GREEN}{CURRENT_MATCH_URL}{Colors.ENDC}")
    print(f"{Colors.GREEN}{'='*60}{Colors.ENDC}\n")

if __name__ == '__main__':
    try:
        update_thread = threading.Thread(target=auto_update_scores, daemon=True)
        update_thread.start()
        get_user_input()
        port = int(os.environ.get('PORT', 5000))
        app.run(debug=False, host='0.0.0.0', port=port, use_reloader=False)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.CYAN}Server stopped. Goodbye! 👋{Colors.ENDC}")
        sys.exit(0)






