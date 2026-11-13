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


EYE='进化之路 · P3·3'
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
C=['#2f5f8a','#c4763a','#4f7a52','#8a6fa8','#a84d3a','#5f8fa8','#b8963a','#6f695f']
def slots(ids,n=6):
    return '<div class="slots">'+''.join(f'<div class="slot" style="background:{C[i]}">{i}</div>' for i in ids)+''.join('<div class="slot e">·</div>' for _ in range(n-len(ids)))+'</div>'
card("01-一页纸",2200,f"""
<div class="eyebrow">{EYE}</div>
<h1>寄存箱在哪辆车上：<br>cache-aware 路由</h1>
<div class="sub">一页纸 · 两辆车、8 组常客，每辆只装得下约 6 组</div>
<div class="one">
 <div class="h">老做法</div><div>轮询 / 最少连接；有状态服务用会话粘滞，键是用户 id</div>
 <div class="h">哪里失效</div><div>寄存箱按前缀的格子存，不按用户。轮询下每辆车存一份同样的前缀：<b class="orange">几辆车合起来只有一辆车那么大</b></div>
 <div class="h">新方案</div><div>按 prompt 前缀哈希选车；热车排队比重搬还久时才改道<br><span class="strike">轮询</span>　<span class="strike">最少连接</span>　<span class="strike">按用户 id 哈希</span></div>
 <div class="h">怎么验</div><div>轮询 vs 前缀哈希。盯每辆车 hits / queries、完成条数、TTFT p90<br><span class="gray">回滚信号：命中掉回轮询水平，或一辆车长期 > 2 倍另一辆</span></div>
</div>
<div class="lbl">轮询 · 每辆车都在装 8 组，装不下就互相挤 <span class="gray" style="font-weight:500">（示意）</span></div>
<div class="cars"><div class="car"><div class="t">车 A · 命中 68%</div>{slots([0,5,2,7,3,4])}</div><div class="car"><div class="t">车 B · 命中 64%</div>{slots([1,6,0,4,2,7])}</div></div>
<div class="lbl">前缀哈希 · 每辆车只装自己的 4 组 <span class="gray" style="font-weight:500">（示意）</span></div>
<div class="cars"><div class="car"><div class="t">车 A · 命中 95%</div>{slots([0,1,3,6])}</div><div class="car"><div class="t">车 B · 命中 95%</div>{slots([2,4,5,7])}</div></div>
<div class="callout"><b>选车决定行李搬几遍：</b>150 s 里轮询没命中 226 条，前缀哈希 9 条——8 组各自的第一次，加 1 条。</div>
<div class="note">exp7 · Qwen3-0.6B × 2 · 同一张 RTX 4060 8 GB · 每辆 9,952 token · 8 组 × 1,536 token 前缀 · 并发 8 · 每组 150 s</div>
""")
card("02-命中与均衡",1600,f"""
<div class="eyebrow">{EYE}</div>
<h1>什么时候该改道</h1>
<div class="sub">书 9.5：首字时间 = 排队与行李就绪取大，再加剩下的计算</div>
<div class="frm">T<sub>first</sub> = max(Q, R) + C<small>Q 排队 · R 行李就绪（命中 0，没命中重搬或远程取）· C 剩余计算</small></div>
<div class="lane">
 <div class="box"><h3>热车 · 有寄存箱</h3><div class="cap">R ≈ 0，Q = 排队</div><div class="big" style="margin-top:18px">Q<sub style="font-size:40px">热</sub></div></div>
 <div class="box"><h3>冷车 · 没寄存箱</h3><div class="cap">Q ≈ 0，R = 重搬 1.5K</div><div class="big orange" style="margin-top:18px">≈ 160 ms</div></div>
</div>
<div class="callout" style="margin-top:30px">改道划算的条件：<b>Q<sub>热</sub> &gt; R<sub>重搬</sub></b>。exp7 里 Q<sub>热</sub> ≈ 0，有界哈希改道 14%，每一条都白付 160 ms：命中 95% → 79–87%，p90 68 → 230 ms。</div>
<table><tr><th>跨车搬 176 MB 寄存箱</th><th>用时</th><th>对比重搬 160 ms</th></tr>
<tr><td>PCIe Gen4 x16（理论 32 GB/s）</td><td>≈ 6 ms</td><td><b>搬</b></td></tr>
<tr><td>10GbE（1.25 GB/s）</td><td>≈ 141 ms</td><td>交点附近</td></tr>
<tr><td>交点 r = 每 token KV ÷ 每 token 重搬</td><td colspan="2">0.6B ≈ 1.1 GB/s · 1.7B ≈ 0.38 · 书 8B/A100 1.41</td></tr></table>
""")
