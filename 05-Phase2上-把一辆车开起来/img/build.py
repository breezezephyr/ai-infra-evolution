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

card('01-环境',1260,f"""
<div class="eyebrow">{EYE}</div>
<h1>一张卡，一块面板</h1>
<div class="sub">计划里的 <span class="strike">24–48 GB 租卡 · 8B</span> 砍成手边的 8 GB</div>
<div class="grid3">
 <div class="box"><h3>卡</h3><div class="big orange">8 GB</div><div class="cap">RTX 4060 Laptop<br>窗口内停 embedding，结束恢复</div></div>
 <div class="box"><h3>模型</h3><div class="big orange">1.7B</div><div class="cap">Qwen3-1.7B BF16<br>权重 3.2 GiB，一圈读一遍</div></div>
 <div class="box"><h3>座位</h3><div class="big orange">13,184</div><div class="cap">token · KV cache<br>utilization 0.90 之后剩下的</div></div>
</div>
<div class="callout"><b>面板六行</b>＝生命周期图六段：站台 · 座位 · 搬行李 · 跑圈 · 下车 · 吞吐。Prometheus 每 2 s 抓一次，Grafana 按 P1·下 那张图排。</div>
<div class="note">vLLM 0.8.5 V1 · vllm bench serve · random 数据集 · ignore_eos</div>
""")
card('02-空车地板',1200,f"""
<div class="eyebrow">{EYE}</div>
<h1>空车：一个人的地板</h1>
<div class="sub">1024 进 · 256 出 · 并发 1。客户端 JSON 与服务端直方图各算一次</div>
<table><tr><th></th><th>客户端</th><th>服务端</th></tr>
<tr><td>首字 TTFT</td><td>128 ms</td><td>129 ms</td></tr>
<tr><td>每字 TPOT</td><td><b>15.4 ms</b></td><td><b>15.4 ms</b></td></tr>
<tr><td>搬行李 每 token</td><td>—</td><td>125 µs</td></tr></table>
<div class="eq"><div class="n">3.4 GB<small>BF16 权重</small></div><div class="op">÷</div><div class="n">256 GB/s<small>显存带宽</small></div><div class="op">=</div><div class="n orange">13.3 ms<small>理论最短一圈</small></div></div>
<div class="callout">实测 15.4 ms，效率 86%。<b>跑圈在等油</b>——01 篇那句话在这张卡上是一个能自己算出来的数。</div>
""")
card('03-座位账',1300,f"""
<div class="eyebrow">{EYE}</div>
<h1>座位账</h1>
<div class="sub">13,184 ÷ 1280 ≈ 10 · 并发 1 → 32，三段形状</div>
<div class="steps">
 <div class="step"><div class="n">1→8</div><div><div class="t">一圈油钱固定</div><div class="d">ITL 15.3 → 19.8 ms（+30%），吞吐 63 → 341 tok/s（×5.4）。running 台阶一格不差</div></div></div>
 <div class="step"><div class="n">8→16</div><div><div class="t">座位到顶</div><div class="d">running 峰 12，KV 99.5%，92 次抢占。ITL p99 21 → 54 ms；TPOT 中位 24.6 > ITL 中位 21.5，差的是重搬</div></div></div>
 <div class="step"><div class="n">16→32</div><div><div class="t">多出来的人全在站台</div><div class="d">吞吐不变 374 tok/s；waiting 峰 23，TTFT 1.8 s → 14.8 s</div></div></div>
</div>
<div class="callout"><b>max_num_seqs=256 从没起作用。</b>小卡上「坐几人」是座位算出来的，不是配置写的。</div>
""")
