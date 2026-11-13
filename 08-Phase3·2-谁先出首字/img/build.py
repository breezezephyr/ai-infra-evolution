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


EYE='进化之路 · P3·2'
CSS += """
.one{display:grid;grid-template-columns:170px 1fr;gap:0;margin-top:40px;background:#fff;border:2px solid #e6e0d4;border-radius:22px;overflow:hidden;flex-shrink:0}
.one>div{padding:26px 30px;border-bottom:2px solid #eee8dc;font-size:29px;line-height:1.55}
.one>.h{background:#f3eee3;font-weight:800;color:#6f695f;font-size:27px}
.one>div:nth-last-child(-n+2){border-bottom:0}
"""

CSS += """
.tl{display:flex;height:84px;border-radius:14px;overflow:hidden;margin-top:18px;border:2px solid #e6e0d4;background:#fff}
.tl div{display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:700;color:#fff}
.lbl{font-size:26px;font-weight:700;margin-top:30px}
"""
card("01-一页纸",1860,f"""
<div class="eyebrow">{EYE}</div>
<h1>谁先出首字：<br>交互与批处理同车</h1>
<div class="sub">一页纸 · 多租户降级，门口管顺序，调度器管那一圈</div>
<div class="one">
 <div class="h">老做法</div><div>优先级队列、按租户配额；满了先拒低优</div>
 <div class="h">哪里失效</div><div>顺序只管到站台为止，上了车大家同一圈。高优排到队首、放不下也没用：<b class="orange">优先级只管顺序，不留座位</b></div>
 <div class="h">新方案</div><div>门口按优先级出队 + 给高优<b class="orange">预留座位</b>；车上那一圈交给每圈预算<br><span class="strike">只排序不预留</span>　<span class="strike">靠抢占腾位置</span></div>
 <div class="h">怎么验</div><div>透传 / FCFS / 优先级 / + 预留四组对照。盯高优 TTFT p99、被卡过占比、低优 tok/s<br><span class="gray">回滚信号：高优 p99 回到秒级，或低优吞吐掉超过一成</span></div>
</div>
<div class="grid3">
 <div class="box"><h3>门口 FCFS</h3><div class="big">4.29 s</div><div class="cap">交互首字 p50<br>p99 6.04 s</div></div>
 <div class="box"><h3>+ 优先级</h3><div class="big green">0.07 s</div><div class="cap">p50 ÷60<br>p99 仍 6.57 s</div></div>
 <div class="box"><h3>+ 预留 1000</h3><div class="big green">0.86 s</div><div class="cap">p99<br>批处理 152 → 153 tok/s</div></div>
</div>
<div class="callout"><b>门口能决定谁先上车，留座位才能保证上得去；上车之后跟谁同一圈，归调度器管。</b></div>
<div class="note">exp6 · 1 路交互（256/64）+ 7 路批处理（2K/256）· Qwen3-1.7B · RTX 4060 8 GB · 网关预算 12,000 · 每组 150 s</div>
""")
card("02-车上那一圈",1500,f"""
<div class="eyebrow">{EYE}</div>
<h1>门管不到的<br>那 0.8 秒</h1>
<div class="sub">优先级组交互 p90 ≈ 0.8 s：网关里排队 0 ms，从放行到首字 786–840 ms</div>
<div class="lbl">平常的一圈 · 车上 5 人各出一个字</div>
<div class="tl"><div style="width:3%;background:#4f7a52"></div><div style="width:97%;background:#fff;color:#4f7a52;justify-content:flex-start;padding-left:18px">≈ 21 ms</div></div>
<div class="lbl">交互上车那一圈 · 应是正赶上一路批处理整块搬 2.4K 行李</div>
<div class="tl"><div style="width:3%;background:#4f7a52"></div><div style="width:97%;background:#c4763a">批处理 prefill 2.4K · 预算 8192 一圈搬完</div></div>
<div class="cap" style="font-size:24px;color:#6f695f;margin-top:10px">≈ 0.8 s，车上所有人一起等，包括刚插队进来的交互</div>
<table><tr><th>办法</th><th>在哪一层</th><th>代价</th></tr>
<tr><td>每圈预算调小</td><td>vLLM 启动参数</td><td>所有人 ITL p99 随行李涨</td></tr>
<tr><td>调度器按优先级排</td><td>vLLM ≥ 0.10 V1</td><td>升级；低优被抢占重搬</td></tr>
<tr><td>交互与批处理分车</td><td>部署</td><td>两辆车各自半满（P3·4）</td></tr></table>
<div class="callout"><b>每圈预算 = 老乘客最多等多久，也是新乘客首字最多等多久。</b></div>
""")
