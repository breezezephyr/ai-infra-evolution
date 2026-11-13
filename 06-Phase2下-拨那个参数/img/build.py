import os, subprocess, pathlib
D=pathlib.Path(__file__).parent
CSS='''
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;background:#f8f5ee;color:#1c1a17;font-family:"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;-webkit-font-smoothing:antialiased}
body{padding:72px 76px;display:flex;flex-direction:column}
.eyebrow{display:flex;align-items:center;gap:14px;color:#8a8378;font-size:26px;letter-spacing:.04em;font-family:Menlo,"SF Mono",monospace}
.eyebrow::before{content:"";width:34px;height:5px;background:#c4763a;border-radius:3px}
h1{font-size:74px;line-height:1.18;font-weight:800;letter-spacing:-.01em;margin-top:34px}
.sub{color:#6f695f;font-size:32px;margin-top:22px;line-height:1.5}
.card{background:#fff;border:2px solid #e6e0d4;border-radius:22px;padding:34px 38px;margin-top:44px}
.callout{background:#fbf1e6;border:2px solid #f0dcc4;border-radius:18px;padding:32px 36px;font-size:32px;line-height:1.6;margin-top:40px;color:#2a2620}
.callout b{color:#1c1a17}
.note{color:#9a9386;font-size:24px;margin-top:auto;padding-top:36px;line-height:1.5}
.blue{color:#c4763a}.orange{color:#c4763a}.green{color:#4f7a52}.gray{color:#9a9386}.red{color:#a84d3a}
.mono{font-family:Menlo,"SF Mono",monospace}
.row{display:flex;align-items:center;justify-content:space-between;padding:26px 0;border-bottom:2px solid #eee8dc;font-size:32px}
.row:last-child{border-bottom:0}
.card>div:last-child{border-bottom:0!important}
.row .k{font-weight:600}.row .v{font-weight:700}
.strike{text-decoration:line-through;text-decoration-thickness:4px;text-decoration-color:#a84d3a;color:#9a9386}
.tag{display:inline-block;font-size:22px;padding:4px 14px;border-radius:8px;background:#eee8dc;color:#6f695f;margin-left:12px;vertical-align:middle;font-weight:600}
'''
CSS += '''
.seats{display:grid;grid-template-columns:repeat(12,1fr);gap:8px;margin-top:14px}
.seat{aspect-ratio:1;border-radius:8px;background:#e6e0d4;position:relative}
.seat.p{background:#c4763a}
.seat.l{background:#c4763a}
.seat.p::after{content:"";position:absolute;inset:30%;border-radius:50%;background:#fff;opacity:.9}
.lane{display:grid;grid-template-columns:1fr 1fr;gap:26px;margin-top:40px}
.lane .box{background:#fff;border:2px solid #e6e0d4;border-radius:22px;padding:30px 34px}
.lane h3{font-size:34px;font-weight:800;margin-bottom:6px}
.lane .cap{font-size:24px;color:#6f695f;line-height:1.45}
.big{font-size:86px;font-weight:800;line-height:1;letter-spacing:-.02em}
.formula{font-family:Menlo,monospace;font-size:30px;background:#fff;border:2px solid #e6e0d4;border-radius:18px;padding:26px 30px;margin-top:36px;line-height:1.6}
.formula b{color:#c4763a}
.bus{display:flex;gap:6px;margin-top:30px}
.bus .car{flex:1;height:120px;border-radius:14px;background:#c4763a;color:#fff;display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:700;position:relative}
.bus .car::after{content:"";position:absolute;right:-6px;top:50%;width:6px;height:16px;background:#9a9386;transform:translateY(-50%)}
.bus .car:last-child::after{display:none}
'''

def card(name, h, body, extra_css=''):
    html=f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{extra_css}html,body{{height:{h}px}}</style></head><body>{body}</body></html>'
    p=D/f'{name}.html'; p.write_text(html)
    subprocess.run(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=2',f'--window-size=1080,{h}',f'--screenshot={D}/{name}.png',f'file://{p}'],capture_output=True)
    print(name)
CSS += """
.steps{display:flex;flex-direction:column;gap:14px;margin-top:40px}
.step{display:grid;grid-template-columns:130px 1fr;gap:20px;align-items:center;background:#fff;border:2px solid #e6e0d4;border-radius:18px;padding:22px 28px}
.step .n{font-family:Menlo,monospace;font-size:38px;font-weight:800;color:#c4763a}
.step .t{font-size:32px;font-weight:800}
.step .d{font-size:24px;color:#6f695f;margin-top:4px;line-height:1.45}
"""
CSS += """
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:40px}
.box{background:#fff;border:2px solid #e6e0d4;border-radius:22px;padding:30px 32px}
.box h3{font-size:34px;font-weight:800}
.box .cap{font-size:24px;color:#6f695f;line-height:1.5;margin-top:10px}
.box .big{font-size:64px;font-weight:800;line-height:1.1;margin-top:8px;letter-spacing:-.02em}
table{width:100%;border-collapse:collapse;margin-top:36px;font-size:28px;background:#fff;border:2px solid #e6e0d4;border-radius:18px;overflow:hidden}
th,td{padding:18px 22px;text-align:left;border-bottom:2px solid #eee8dc}
th{background:#f3eee3;font-weight:700;color:#6f695f;font-size:24px}
tr:last-child td{border-bottom:0}
td b{color:#c4763a}
.eq{display:flex;align-items:center;justify-content:center;gap:28px;margin-top:44px;font-size:40px;font-weight:800}
.eq .n{background:#fff;border:2px solid #e6e0d4;border-radius:18px;padding:22px 30px;text-align:center}
.eq .n small{display:block;font-size:22px;color:#6f695f;font-weight:500;margin-top:6px}
.eq .op{color:#9a9386}
"""

EYE='进化之路 · P2·上'
EYE2='进化之路 · P2·下'

card('01-两面对上',1700,f"""
<div class="eyebrow">{EYE2}</div>
<h1>两面对上</h1>
<div class="sub">同一批请求：客户端 bench JSON vs 服务端 Prometheus 直方图，18 个窗口</div>
<table><tr><th>指标</th><th>客户端</th><th>服务端</th><th>差</th></tr>
<tr><td>TPOT · 全部窗口</td><td>15.4 … 33.3 ms</td><td>同值</td><td><b>≤ 0.2 ms</b></td></tr>
<tr><td>TTFT · 并发 ≤ 8</td><td>128 / 395 / 860 ms</td><td>129 / 384 / 839 ms</td><td>≤ 3%</td></tr>
<tr><td>TTFT · 并发 32</td><td>14.1 s</td><td>14.9 s</td><td>服务端高 6%</td></tr>
<tr><td>e2e · 并发 1</td><td>4054 ms</td><td>4320 ms</td><td>服务端高 6.6%</td></tr></table>
<div class="steps" style="margin-top:34px">
 <div class="step"><div class="n">+1</div><div><div class="t">条数差一条</div><div class="d">压测工具先发一条探针；正式第一条命中探针留下的寄存箱，TTFT 只有 20 ms</div></div></div>
 <div class="step"><div class="n">+5%</div><div><div class="t">token 数不一样</div><div class="d">random 数据集 token id → 文本 → 服务端重新分词，「输入 1024」是名义值</div></div></div>
 <div class="step"><div class="n">1.5 s</div><div><div class="t">直方图 ≠ 排队 + 搬行李</div><div class="d">重载下进 API server 到进 waiting 队列之间的一段，客户端看不见</div></div></div>
</div>
<div class="callout"><b>客户端看得到形状，服务端看得到原因。对账先对条数。</b></div>
""")
card('02-一张表看全部',1180,f"""
<div class="eyebrow">{EYE2}</div>
<h1>服务端一张表看全部</h1>
<div class="sub">每个窗口的峰值 · Prometheus</div>
<table><tr><th>窗口</th><th>抢占</th><th>running 峰</th><th>waiting 峰</th><th>KV 峰</th></tr>
<tr><td>exp1 并发 1–32</td><td>92</td><td>12</td><td>23</td><td>100%</td></tr>
<tr><td>exp2 预算 2048 / 8192</td><td>13 / 5</td><td>4</td><td>3</td><td>98%</td></tr>
<tr><td>exp3 寄存 关 / 开</td><td>2 / <b>0</b></td><td>4</td><td>1 / 0</td><td>87% / <b>29%</b></td></tr>
<tr><td>exp4 座位 5.7K · 并发 8 / 16</td><td>17 / 35</td><td>5</td><td>4 / 12</td><td>100%</td></tr></table>
<div class="callout">exp3 那一行是全天最干净的对照：同样 4 个人、同样 3K 行李，共用格子后座位 87% → 29%，抢占 2 → 0。<b>共用座位省下的抢占，也算在跑圈头上。</b></div>
""")
