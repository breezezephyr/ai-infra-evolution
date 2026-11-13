import os, subprocess, pathlib
D=pathlib.Path(__file__).parent
CSS='''
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;background:#f8f5ee;color:#1c1a17;font-family:"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;-webkit-font-smoothing:antialiased}
body{padding:72px 76px;display:flex;flex-direction:column}
.eyebrow{display:flex;align-items:center;gap:14px;color:#8a8378;font-size:26px;letter-spacing:.04em;font-family:Menlo,"SF Mono",monospace}
.eyebrow::before{content:"";width:34px;height:5px;background:#2f5f8a;border-radius:3px}
h1{font-size:74px;line-height:1.18;font-weight:800;letter-spacing:-.01em;margin-top:34px}
.sub{color:#6f695f;font-size:32px;margin-top:22px;line-height:1.5}
.card{background:#fff;border:2px solid #e6e0d4;border-radius:22px;padding:34px 38px;margin-top:44px}
.callout{background:#fbf1e6;border:2px solid #f0dcc4;border-radius:18px;padding:32px 36px;font-size:32px;line-height:1.6;margin-top:40px;color:#2a2620}
.callout b{color:#1c1a17}
.note{color:#9a9386;font-size:24px;margin-top:auto;padding-top:36px;line-height:1.5}
.blue{color:#2f5f8a}.orange{color:#c4763a}.green{color:#4f7a52}.gray{color:#9a9386}.red{color:#a84d3a}
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
.seat.p{background:#2f5f8a}
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
.bus .car{flex:1;height:120px;border-radius:14px;background:#2f5f8a;color:#fff;display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:700;position:relative}
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
.step{display:grid;grid-template-columns:110px 1fr;gap:20px;align-items:center;background:#fff;border:2px solid #e6e0d4;border-radius:18px;padding:22px 28px}
.step .n{font-family:Menlo,monospace;font-size:44px;font-weight:800;color:#2f5f8a}
.step .t{font-size:32px;font-weight:800}
.step .d{font-size:24px;color:#6f695f;margin-top:4px;line-height:1.45}
.loop{text-align:center;color:#9a9386;font-size:26px;margin-top:10px}
.blocks{display:grid;grid-template-columns:repeat(8,1fr);gap:8px;margin-top:12px}
.blk{height:64px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-family:Menlo,monospace;font-size:22px;color:#fff;background:#2f5f8a}
.blk.s{background:#4f7a52}.blk.o{background:#c4763a}.blk.e{background:#e6e0d4;color:#9a9386}
.who{font-size:24px;color:#6f695f;margin-top:22px}
.node{display:inline-block;padding:14px 26px;border-radius:14px;font-size:28px;font-weight:800;color:#fff;background:#2f5f8a}
.node.g{background:#9a9386}.node.d{background:#4f7a52}
.arrow{color:#9a9386;font-size:30px;padding:0 14px}
.kv{display:grid;grid-template-columns:230px 1fr;gap:18px;padding:22px 0;border-bottom:2px solid #eee8dc;font-size:27px;line-height:1.45}
.kv:last-child{border-bottom:0}
.kv .k{font-weight:700}
.metric{font-family:Menlo,monospace;font-size:20px;color:#2f5f8a;background:#e8eef4;border-radius:6px;padding:3px 10px;display:inline-block;margin:6px 6px 0 0}
"""
EYE='<div class="eyebrow">进化之路 · P1·下</div>'
card('01-行李架账本',1600,f'''{EYE}<h1>行李架的账本：<br>格子、清单、共用</h1><div class="sub">PagedAttention 的 paged。默认 16 个 token 一格。</div>
<div class="card"><div class="who">乘客 A 的清单 → 物理格子</div>
<div class="blocks"><div class="blk s">#37</div><div class="blk s">#04</div><div class="blk s">#12</div><div class="blk">#51</div><div class="blk">#08</div><div class="blk e">·</div><div class="blk e">·</div><div class="blk e">·</div></div>
<div class="who">乘客 B 的清单 → 前 3 格和 A 是同一批（相同前缀，引用计数 2）</div>
<div class="blocks"><div class="blk s">#37</div><div class="blk s">#04</div><div class="blk s">#12</div><div class="blk o">#22</div><div class="blk e">·</div><div class="blk e">·</div><div class="blk e">·</div><div class="blk e">·</div></div>
<div style="display:flex;gap:24px;margin-top:18px;font-size:22px;color:#6f695f"><span><span class="blk s" style="display:inline-block;width:22px;height:22px;border-radius:5px;vertical-align:middle"></span> 共用</span><span><span class="blk" style="display:inline-block;width:22px;height:22px;border-radius:5px;vertical-align:middle"></span> A 私有</span><span><span class="blk o" style="display:inline-block;width:22px;height:22px;border-radius:5px;vertical-align:middle"></span> B 私有</span></div></div>
<div class="card" style="padding:6px 38px">
<div class="kv"><div class="k">认出两箱一样</div><div>格 hash = 上一格 hash + 本格 token；<b>只有满格才进缓存</b></div></div>
<div class="kv"><div class="k">碎片</div><div>整段预留 64 容量浪费 22；4 token 一格 52 容量浪费 10</div></div>
<div class="kv"><div class="k">共用省多少</div><div>16 条长请求独立 19,008 MiB；共享 6K 前缀 <b>5,910 MiB</b></div></div>
<div class="kv"><div class="k">释放</div><div>引用计数归零进空闲队列，LRU 淘汰</div></div></div>''')

card('02-投机解码',1520,f'''{EYE}<h1>跟班先猜，<br>司机一圈验完</h1><div class="sub">司机验 k 个字和出 1 个字花的时间差不多——跑圈本来在等油。</div>
<div class="lane">
<div class="box"><h3 style="color:#2f5f8a">猜得准</h3><div class="cap">接受率 α = 3/4，猜 4 个</div><div class="big" style="color:#2f5f8a;margin-top:18px">3.05</div><div class="cap">平均一圈拿几个字<br>1 + α + α² + α³ + α⁴</div></div>
<div class="box"><h3 style="color:#c4763a">猜不准</h3><div class="cap">接受率 α = 1/4，猜 4 个</div><div class="big" style="color:#c4763a;margin-top:18px">1.33</div><div class="cap">白跑了跟班那一趟</div></div></div>
<div class="card" style="padding:6px 38px">
<div class="row"><span class="k">普通 decode</span><span class="mono">90.0 ms</span></div>
<div class="row"><span class="k">猜 7 个（K7）</span><span><span class="mono">30.6 ms</span>　<b style="color:#2f5f8a">2.94×</b></span></div>
<div class="row"><span class="k">猜 15 个（K15）</span><span><span class="mono">29.4 ms</span>　只再快 1.2 ms</span></div></div>
<div class="callout"><b>空车时的加速器。</b> 满车时每圈算力已吃紧，再多验 k 个位置就撞发动机；跟班自己也占算力。晚上快，高峰没感觉。</div>
<div class="note">验证用拒绝采样，接受概率 min(1, p_target / p_draft)，输出分布不变。</div>''')

card('03-生命周期图',1560,f'''{EYE}<h1>一位乘客的一生，<br>和每个节点的指标</h1><div class="sub">这张图就是 Phase 2 那块面板的布局：每个节点一条曲线。</div>
<div class="card" style="text-align:center;padding:40px 30px">
<div><span class="node g">站台 waiting</span><span class="arrow">→</span><span class="node">车上 running</span><span class="arrow">→</span><span class="node d">下车 finished</span></div>
<div style="margin-top:26px;font-size:24px;color:#c4763a">↑ 被请下车（抢占）回站台<b>队头</b>，行李重搬 ↰</div>
<div style="text-align:left;margin-top:30px">
<div class="who" style="margin-top:0">站台</div><span class="metric">num_requests_waiting</span><span class="metric">request_queue_time_seconds</span>
<div class="who">上车 · 决定 2</div><span class="metric">kv_cache_usage_perc</span><span class="metric">prefix_cache_hits / queries</span>
<div class="who">搬行李 · 决定 4</div><span class="metric">request_prefill_time_seconds</span><span class="metric">time_to_first_token_seconds</span>
<div class="who">每圈一个字 · 决定 1 + 4</div><span class="metric">num_requests_running</span><span class="metric">inter_token_latency_seconds</span>
<div class="who">被请下车 · 决定 3</div><span class="metric">num_preemptions_total</span>
<div class="who">下车</div><span class="metric">request_success_total</span><span class="metric">e2e_request_latency_seconds</span></div></div>
<div class="note">V0 的 num_requests_swapped 在 V1 没有了——储物柜拆了。指标前缀 vllm:。</div>''')
