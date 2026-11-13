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


EYE='进化之路 · P3·4'
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

CSS += """
.cars{display:grid;grid-template-columns:1fr 1fr;gap:26px;margin-top:22px}
.car{background:#fff;border:2px solid #e6e0d4;border-radius:18px;padding:20px 24px}
.car .t{font-size:24px;color:#6f695f;font-weight:700;margin-bottom:12px}
.slots{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.slot{height:54px;border-radius:10px;display:flex;align-items:center;justify-content:center;font:700 24px Menlo,monospace;color:#fff}
.slot.e{background:#eee8dc;color:#9a9386}
.frm{font-family:Menlo,monospace;font-size:46px;font-weight:800;text-align:center;margin-top:36px;background:#fff;border:2px solid #e6e0d4;border-radius:18px;padding:28px}
.frm small{display:block;font:500 24px "PingFang SC";color:#6f695f;margin-top:10px}
"""

card("01-一页纸",1950,f"""
<div class="eyebrow">{EYE}</div>
<h1>拆车：PD 分离<br>与这张卡的配比</h1>
<div class="sub">一页纸 · μ_PD = min(μ_P, μ_D, B_net / V_KV)，全部代入实测数</div>
<div class="one">
 <div class="h">老做法</div><div>读写分离：写库一套、读库一套，各自扩容</div>
 <div class="h">哪里失效</div><div>P 与 D 之间要传整份 KV：1K 输入 <b class="orange">117 MB</b>。还丢了合车白拿的好处：搬行李搭跑圈的便车</div>
 <div class="h">新方案</div><div>异构卡按配比拆；同构卡先用每圈预算 + 门口留座，拆车留给 ITL 硬约束<br><span class="strike">同构卡一律拆</span>　<span class="strike">按 1:1 拆</span></div>
 <div class="h">怎么验</div><div>同卡数合车 vs 拆车。盯 req/s、ITL p99、TTFT、P→D 链路利用率<br><span class="gray">回滚信号：拆车吞吐 &lt; 合车 80%，或链路利用率 &gt; 70%</span></div>
</div>
<div class="grid3">
 <div class="box"><h3>P 车</h3><div class="big">3.26</div><div class="cap">req/s · 1024 × 300 µs</div></div>
 <div class="box"><h3>D 车</h3><div class="big">1.81</div><div class="cap">req/s · 10 人 × 256 圈 × 21.6 ms</div></div>
 <div class="box"><h3>合车实测</h3><div class="big green">1.45</div><div class="cap">串行估 1.16，多 25%<br>应是搭了便车</div></div>
</div>
<div class="callout"><b>配比 P : D = 1 : 1.8。</b>8 张卡 3P + 5D = 9.0 req/s，合车 11.6：同构卡拆车只有合车的 78%，换来 D 车上没人搬行李。</div>
<div class="note">Qwen3-1.7B · RTX 4060 8 GB · 输入 1024 / 输出 256 · 公式取自 ai-infra-book 9.2</div>
""")
card("02-收尾表",1620,f"""
<div class="eyebrow">{EYE}</div>
<h1>Phase 3 收尾：<br>四个旋钮，线上谁拨</h1>
<div class="sub">P2 说每个旋钮动哪条线；P3 说谁来拨、拨错了看什么</div>
<table><tr><th>旋钮</th><th>谁拨</th><th>拨法</th><th>拨错了</th></tr>
<tr><td><b>并发</b><br><span class="gray">P3·1</span></td><td>网关</td><td>按 in + max_tokens 预留准入；429 配退避</td><td>waiting 持续 &gt; 0</td></tr>
<tr><td><b>每圈预算</b><br><span class="gray">P3·2</span></td><td>调度器 + 网关排序</td><td>高优插队 + 留座；那一圈交给调度器</td><td>高优 p99 回到秒级</td></tr>
<tr><td><b>寄存箱</b><br><span class="gray">P3·3</span></td><td>路由</td><td>前缀哈希；热车排队 &gt; 重搬才改道</td><td>命中掉回轮询水平</td></tr>
<tr><td><b>座位数</b><br><span class="gray">P3·4</span></td><td>容量规划</td><td>同构先不拆；利用率 70% 前扩容</td><td>T_drain 超 SLO 窗口</td></tr></table>
<div class="formula">T<sub>drain</sub> = λ·T<sub>s</sub> / (μ − λ)，停 43 s 后清空：<br>50% → <b>1.4 min</b> · 80% → <b>3.6 min</b> · 90% → <b>7.2 min</b></div>
<div class="callout"><b>并发管站台，每圈预算管那一圈，寄存箱管要不要搬，座位数管车本身。</b></div>
""")
