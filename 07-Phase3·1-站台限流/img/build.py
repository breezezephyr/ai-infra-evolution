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


EYE='进化之路 · P3·1'
CSS += """
.one{display:grid;grid-template-columns:170px 1fr;gap:0;margin-top:40px;background:#fff;border:2px solid #e6e0d4;border-radius:22px;overflow:hidden;flex-shrink:0}
.one>div{padding:26px 30px;border-bottom:2px solid #eee8dc;font-size:29px;line-height:1.55}
.one>.h{background:#f3eee3;font-weight:800;color:#6f695f;font-size:27px}
.one>div:nth-last-child(-n+2){border-bottom:0}
"""
card("01-一页纸",1900,f"""
<div class="eyebrow">{EYE}</div>
<h1>站台限流：<br>按人数还是按行李</h1>
<div class="sub">一页纸 · 旋钮是并发，门开在 vLLM 前面</div>
<div class="one">
 <div class="h">老做法</div><div>网关按 QPS / 连接数限流，超了 429</div>
 <div class="h">哪里失效</div><div>一条请求占的是座位，座位按 token 算。6K 输入的一条 ≈ 256 输入的<b class="orange">二十几条</b>；QPS 不变，行李一变车就挤爆</div>
 <div class="h">新方案</div><div>按 <b class="orange">in + max_tokens</b> 预留座位准入；放不下 → 拒绝或网关排队，都给期限<br><span class="strike">按 QPS</span>　<span class="strike">按连接数</span></div>
 <div class="h">怎么验</div><div>对照：透传 / 429 / 网关排队。盯上车者 TTFT p99、ITL p99、拒绝率、抢占<br><span class="gray">回滚信号：waiting 持续不为零，或 ITL p99 回到透传水平</span></div>
</div>
<div class="grid3">
 <div class="box"><h3>透传</h3><div class="big">14.6 s</div><div class="cap">首字 p50 · 抢占 60<br>ITL p99 52 ms</div></div>
 <div class="box"><h3>按 token 准入</h3><div class="big green">0.9 s</div><div class="cap">首字 p50 · 抢占 0<br>ITL p99 22 ms</div></div>
 <div class="box"><h3>吞吐</h3><div class="big gray">≈ 同</div><div class="cap">351–385 tok/s<br>车一直是满的</div></div>
</div>
<div class="callout"><b>限流数的是行李，不是人头；门只决定人在哪里等，吞吐由座位定。</b></div>
<div class="note">exp5 · Qwen3-1.7B · RTX 4060 8 GB · 座位 13,184 token · 预算 12,000 · 并发 32 × 256 条</div>
""")
card('02-两种超时',1500,f"""
<div class="eyebrow">{EYE}</div>
<h1>两种超时，<br>杀的是两种人</h1>
<div class="sub">流式接口的首字超时与字间停滞，常被配成同一个数</div>
<div class="lane">
 <div class="box"><h3>首字超时</h3><div class="cap">等的是：排队 + 搬行李</div>
  <div class="big" style="margin-top:22px">站台上</div><div class="cap" style="margin-top:14px">浪费：几乎为零<br>兜底：早告知、退避、降级</div></div>
 <div class="box"><h3>字间停滞</h3><div class="cap">等的是：下一圈 / 被请下车重搬</div>
  <div class="big red" style="margin-top:22px">车上</div><div class="cap" style="margin-top:14px">浪费：已搬的行李全作废<br>兜底：别让抢占发生；续传或重试</div></div>
</div>
<table><tr><th>首字期限 5 s · 实测</th><th>数</th></tr>
<tr><td>网关 504</td><td>172</td></tr>
<tr><td>vLLM <span class="mono">Aborted request</span></td><td>172</td></tr>
<tr><td>被杀者搬过的 prompt token</td><td><b>0</b></td></tr>
<tr><td>车上的人 ITL p99</td><td><b>136.6 ms</b>（透传 52）</td></tr></table>
<div class="callout">期限到 → 一批人 abort → 空位 → 站台的人涌进来搬行李 → 老乘客每圈被拖。<b>杀站台上的人不浪费算力，但把车上的人颠了一下。</b></div>
""")
