import subprocess, pathlib
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
.note{color:#9a9386;font-size:24px;margin-top:28px;padding-top:0;line-height:1.5}
.blue{color:#c4763a}.orange{color:#c4763a}.green{color:#4f7a52}.gray{color:#9a9386}.red{color:#a84d3a}
.mono{font-family:Menlo,"SF Mono",monospace}
.strike{text-decoration:line-through;text-decoration-thickness:4px;text-decoration-color:#a84d3a;color:#9a9386}
'''
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
"""
EYE='进化之路 · P3b·1'
CSS += """
.one{display:grid;grid-template-columns:170px 1fr;gap:0;margin-top:40px;background:#fff;border:2px solid #e6e0d4;border-radius:22px;overflow:hidden;flex-shrink:0}
.one>div{padding:26px 30px;border-bottom:2px solid #eee8dc;font-size:29px;line-height:1.55}
.one>.h{background:#f3eee3;font-weight:800;color:#6f695f;font-size:27px}
.one>div:nth-last-child(-n+2){border-bottom:0}
"""

def card(name, h, body, extra_css=''):
    html=f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{extra_css}html,body{{height:{h}px}}</style></head><body>{body}</body></html>'
    p=D/f'{name}.html'; p.write_text(html)
    subprocess.run(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=2',f'--window-size=1080,{h}',f'--screenshot={D}/{name}.png',f'file://{p}'],capture_output=True)
    print(name, h)

card("01-一页纸",1820,f"""
<div class="eyebrow">{EYE}</div>
<h1>车库：出一辆<br>新车要多久</h1>
<div class="sub">一页纸 · 出车 27–44 s，信号要提前这么多才买得起</div>
<div class="one">
 <div class="h">老做法</div><div>HPA 看 GPU 利用率拉新实例<br>下线直接杀进程</div>
 <div class="h">哪里失效</div><div>利用率在 λ = 38% μ 时就到 90%<br>队列信号超标前 <b class="orange">1–9 s</b> 才响，出车要 27–44 s<br>等 10 秒再断，白跑的字比立刻断还多</div>
 <div class="h">新方案</div><div>到达率 λ̂ ≥ 70% μ 就出车，编译缓存预烤<br>graph 只捕获用得上的尺寸<br>期限 = max_tokens × ITL；短了就立刻断、续传<br><span class="strike">看 GPU 利用率</span>　<span class="strike">给 10 秒优雅退出</span></div>
 <div class="h">怎么验</div><div>启动分段计时；爬坡比提前量；四档期限比白跑字数<br><span class="gray">不成立：提前量 &lt; 出车时间，或白跑随期限上升</span></div>
</div>
<div class="grid3">
 <div class="box"><h3>日常重启</h3><div class="big">44 s</div><div class="cap">CUDA graph 占 16 s<br>读权重只占 3%</div></div>
 <div class="box"><h3>6 个尺寸</h3><div class="big green">27 s</div><div class="cap">graph 16 → 1.1 s<br>ITL 不变</div></div>
 <div class="box"><h3>到达率</h3><div class="big">35 s</div><div class="cap">λ̂ ≥ 70% μ<br>够 27 s，不够 44 s</div></div>
</div>
<div class="callout"><b>地板约 24 秒，和权重大小无关。</b><br>要比这快，只能常驻热备。队列信号来不及叫车。</div>
<div class="note">Qwen3-1.7B · 3.2 GiB · RTX 4060 8 GB · vLLM 0.8.5 · exp8–10 · μ = 1.45 req/s</div>
""")

card("02-切流窗口",1360,f"""
<div class="eyebrow">{EYE}</div>
<h1>多机房：窗口看<br>对面有没有热车</h1>
<div class="sub">纸面 · T_cut = T_detect + T_start + T_drain</div>
<table>
<tr><th>情形</th><th>合计</th><th>大头</th></tr>
<tr><td>一地故障，冷启动</td><td><b>74 秒</b></td><td>平时各 70%；6 尺寸则 46 秒</td></tr>
<tr><td>平时就在 90%</td><td><b>3.8 分钟</b></td><td>余量 0.28 req/s，再清约 3 分钟</td></tr>
<tr><td>对面没有卡</td><td><b>限流</b></td><td>拒约 29%，队伍只涨不跌</td></tr>
<tr><td>发布日 ×10</td><td><b>5.3 分钟</b></td><td>冷启动到 8 张；7 张清不掉</td></tr>
<tr><td>热备事先在</td><td><b>约 3 秒</b></td><td>窗口只剩三次探测</td></tr>
</table>
<div class="callout"><b>京沪约 30 ms，进不了这张表。</b><br>被断的人重搬 0.4 秒；1 Gbps 送 KV 要 1.3 秒，10 Gbps 只要 0.13 秒。</div>
<div class="note">纸面，未实测。μ = 1.45 · T_s 取 exp8 的 44 / 27 s · RTT 与 1 秒探测超时为假设 · 算法见正文第六节</div>
""")
