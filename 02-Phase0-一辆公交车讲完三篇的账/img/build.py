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


EYE='<div class="eyebrow">进化之路 · P0</div>'

# 01 对照表
rows=[('模型权重 140 GB','跑一圈的固定油钱'),('decode 一个 token','车跑一圈，每位乘客拿到一个字'),('prompt / prefill','上车带的行李 / 上车前一次搬上车'),
('KV cache','行李架：上车的行李 + 每圈多出的一件'),('batch','车上同时坐几人'),('KV 预算 59 GB','座位 + 行李架的总容量'),
('prefix cache','常客的行李已按箱寄存'),('TP=8','8 节车厢并排跑，每圈对一次表'),('扩容','从车库开新车，1–2 分钟')]
card('01-对照表',1700,f'''{EYE}<h1>一辛公交车，<br>讲完三篇的账</h1><div class="sub">全篇一个比喻。一个乘客 = 一次请求。</div>
<div class="card" style="padding:6px 38px">'''.replace('一辛','一辆')+''.join(f'''<div class="row"><span class="k mono" style="font-size:28px">{a}</span><span style="color:#2f5f8a;font-weight:600">{b}</span></div>''' for a,b in rows)+'''</div>
<div class="callout">乘客上车时带的行李是 <b>prompt</b>；之后每跑一圈，行李架上多一件——那是他刚拿到的字。</div>''')

# 02 搬行李 vs 跑圈
card('02-搬行李vs跑圈',1300,f'''{EYE}<h1>搬行李靠力气，<br>跑圈靠油钱</h1><div class="sub">两件事互不相干。一次请求 93% 的时间在跑圈。</div>
<div class="lane">
<div class="box"><div style="font-size:24px;color:#c4763a;font-weight:700;letter-spacing:.06em" class="mono">PREFILL</div><h3>搬行李</h3>
<div class="cap">1000 件行李，一队搬运工同时搬<br>瓶颈：<b>力气（算力）</b><br>算力用了 90–95%</div>
<div class="big" style="color:#c4763a;margin-top:26px">7%</div><div class="cap">时间占比</div></div>
<div class="box"><div style="font-size:24px;color:#2f5f8a;font-weight:700;letter-spacing:.06em" class="mono">DECODE</div><h3>跑圈</h3>
<div class="cap">每圈只能给每人送一个字<br>瓶颈：<b>油钱（显存带宽）</b><br>算力只用了 20–40%</div>
<div class="big" style="color:#2f5f8a;margin-top:26px">93%</div><div class="cap">时间占比</div></div></div>
<div class="callout">油管掐细 40%，搬行李只慢 17%；搬运工减一半，跑圈只慢 22%。<b>作用在哪一段，收益上限就是那一段的占比。</b></div>
<div class="note">1000 in / 200 out，H100 SXM5，Llama-3-70B 级，TP=8。</div>''')

# 03 一圈多久 + 为什么 8 节
card('03-一圈6.34ms',1560,f'''{EYE}<h1>一圈最少 6.34 ms，<br>为什么是 8 节车厢</h1><div class="sub">140 GB 的发动机塞不进一节 80 GB 车厢，必须拆。</div>
<div class="bus">'''+''.join(f'<div class="car">17.5 GB</div>' for _ in range(8))+'''</div>
<div style="display:flex;justify-content:space-between;font-size:24px;color:#6f695f;margin-top:10px"><span>8 节同时读各自那份</span><span>每圈对一次表（all-reduce）</span></div>
<div class="formula">17.5 GB ÷ 3.35 TB/s = 5.22 ms<br>+ 80 层 × 2 次对表 ≈ 1.12 ms<br>= <b>6.34 ms / 圈</b></div>
<div class="card" style="padding:10px 38px">
<div class="row"><span class="k">拆 2 节</span><span>装得下，但一圈 70 ÷ 3.35 = <b>20.9 ms</b></span></div>
<div class="row"><span class="k">拆 8 节</span><span style="color:#2f5f8a;font-weight:700">一圈 5.22 ms，单机 8 卡 NVLink 全互联</span></div>
<div class="row"><span class="k">拆 16 节</span><span>要跨机箱，对表带宽从 726 掉到 90 GB/s，差 8 倍</span></div></div>
<div class="callout">8 = <b>不出机箱能并排的最大车厢数</b>。换更强的发动机没用，卡的是油管粗细。</div>''')

# 04 车上空间 + 每人行李
card('04-车上空间',1500,f'''{EYE}<h1>一节车厢里，<br>四分之三是座位</h1><div class="sub">容量规划盯的不是发动机，是座位。</div>
<div class="card"><div style="display:flex;height:74px;border-radius:14px;overflow:hidden;font-size:24px;font-weight:700;color:#fff">
<div style="width:22%;background:#c4763a;display:flex;align-items:center;justify-content:center">22%</div>
<div style="width:4%;background:#9a9386"></div>
<div style="flex:1;background:#2f5f8a;display:flex;align-items:center;justify-content:center">座位 + 行李架 74%</div></div>
<div class="row" style="margin-top:14px"><span class="k">发动机（权重分片 140 ÷ 8）</span><span class="v" style="color:#c4763a">17.5 GB</span></div>
<div class="row"><span class="k">司机座、过道（CUDA 上下文、激活）</span><span class="v gray">~3.5 GB</span></div>
<div class="row"><span class="k">座位 + 行李架（KV 预算）</span><span class="v" style="color:#2f5f8a">59.0 GB</span></div></div>
<div class="formula" style="font-size:27px">每件行李（每 token 的 KV）<br>= 2 (K,V) × 8 组 × 128 × 2 B × 80 层 = <b>328 KB</b>，每节车厢 41 KB</div>
<div class="callout">GQA（分组查询注意力）让 64 个头共用 8 组行李。换 MHA（多头注意力）每件是 2.6 MB——<b>同一辆车少坐 8 倍的人</b>。</div>''')

# 05 batch：一圈多送几人
brow=[('8','18.8 GB','6.74 ms','1×'),('32','22.9 GB','6.83 ms','1/4'),('128','39.0 GB','12.75 ms','1/8.5')]
card('05-batch',1400,f'''{EYE}<h1>一圈油钱固定，<br>多坐人就便宜</h1><div class="sub">batch = 车上坐几人。这是 decode 唯一的分摊手段。</div>
<div class="formula">每圈搬运 = <b>油钱 17.5 GB</b>（与人数无关）<br>+ 人数 × 每人 41 KB × 行李件数 ctx</div>
<div class="card" style="padding:0;overflow:hidden"><div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;font-size:27px">
<div style="padding:22px 26px;background:#f3eee3;font-weight:700">坐几人</div><div style="padding:22px 26px;background:#f3eee3;font-weight:700">每圈搬运</div><div style="padding:22px 26px;background:#f3eee3;font-weight:700">一圈多久</div><div style="padding:22px 26px;background:#f3eee3;font-weight:700">每人每字成本</div>'''+''.join(f'''<div style="padding:22px 26px;border-top:2px solid #eee8dc" class="mono">{a}</div><div style="padding:22px 26px;border-top:2px solid #eee8dc">{b}</div><div style="padding:22px 26px;border-top:2px solid #eee8dc">{c}</div><div style="padding:22px 26px;border-top:2px solid #eee8dc;color:#2f5f8a;font-weight:700">{d}</div>''' for a,b,c,d in brow)+'''</div></div>
<div class="callout">坐 16 倍的人，一圈只慢不到一倍，每人成本降到 1/8.5。<b>连续批处理 = 随上随下</b>，车一直跑，座位不空。</div>
<div class="note">ctx = 4096。fast 档贵 2–3 倍，机制上是「包一辆少载人的车」。</div>''')

# 06 座位约束：行李多，坐的人少
def seats(n_p, per):
    cells=[]
    for i in range(n_p):
        cells.append('<div class="seat p"></div>')
        cells+=['<div class="seat l"></div>']*(per-1)
    cells=cells[:48]
    while len(cells)<48: cells.append('<div class="seat"></div>')
    return '<div class="seats">'+''.join(cells)+'</div>'
card('06-座位约束',1480,f'''{EYE}<h1>行李越多，<br>能坐的人越少</h1><div class="sub">座位是硬约束：人数 × 行李 ≤ 59 GB。同一辆车，48 个格子。</div>
<div class="lane">
<div class="box"><h3 style="color:#2f5f8a">轻装 · ctx 2K</h3><div class="cap">每人 1 格，坐 48 人</div>{seats(48,1)}</div>
<div class="box"><h3 style="color:#c4763a">重装 · ctx 16K</h3><div class="cap">每人 8 格（1 人 + 7 件行李），坐 6 人</div>{seats(6,8)}</div></div>
<div class="card" style="padding:6px 38px">
<div class="row"><span class="k mono">ctx 2K</span><span>坐满 <b>703</b> 人，每字成本 1×</span></div>
<div class="row"><span class="k mono">ctx 8K</span><span>坐满 <b>176</b> 人，4×</span></div>
<div class="row"><span class="k mono">ctx 128K</span><span>坐满 <b>11</b> 人，<b style="color:#c4763a">64×</b></span></div></div>
<div class="callout">行李多不主要让车变慢（坐满时一圈恒为 23.96 ms），<b>它让坐的人变少，每人分摊的油钱变多</b>。两道天花板取小：座位 59 GB ÷ (ctx × 41 KB)，发动机拐点 295 人。</div>''')

# 07 常客寄存
card('07-寄存行李',1560,f'''{EYE}<h1>常客寄存行李：<br>省的是搬，不是跑</h1><div class="sub">按箱寄存，一箱 256 件。前一箱变了，后面全部作废。</div>
<div class="card"><div style="font-size:26px;color:#6f695f;margin-bottom:14px">例：system prompt 3000 件 + 用户问题 50 件</div>
<div style="display:flex;gap:6px;flex-wrap:wrap">'''+''.join('<div style="width:76px;height:56px;border-radius:10px;background:#2f5f8a;color:#fff;font-size:20px;display:flex;align-items:center;justify-content:center;font-weight:700">256</div>' for _ in range(11))+'''<div style="width:58px;height:56px;border-radius:10px;background:#e6e0d4;color:#6f695f;font-size:20px;display:flex;align-items:center;justify-content:center">184</div><div style="width:44px;height:56px;border-radius:10px;background:#c4763a;color:#fff;font-size:20px;display:flex;align-items:center;justify-content:center">50</div></div>
<div style="display:flex;justify-content:space-between;font-size:24px;margin-top:14px"><span style="color:#2f5f8a;font-weight:700">寄存好的：11 箱 = 2816 件</span><span style="color:#6f695f">零碎 184 + 新的 50，都要重搬</span></div></div>
<div class="card" style="padding:6px 38px">
<div class="row"><span class="k">100k 行李寄存好</span><span>延迟 −79%，成本 −90%</span></div>
<div class="row"><span class="k">只有 10k 行李</span><span>延迟只 <b>−31%</b>：本来就没多少要搬</span></div>
<div class="row"><span class="k">10 轮对话</span><span>成本只 <b>−53%</b>：每圈的油钱照付</span></div></div>
<div class="callout">所有厂商只公布首字延迟的改善，没人公布每字间隔的改善——<b>因为那个数本该是 0</b>。</div>
<div class="note">Anthropic 官方实测表。盈亏平衡：多付 0.25 ÷ 每次省 0.9 = 0.28 次命中回本。</div>''')

# 08 调度员约束表
crow=[('93% 在跑圈','优化重心在 decode；多坐人是唯一分摊手段'),('搬行李和跑圈互不相干','站台上搬大件会拖慢全车 → chunked prefill / PD 分离'),
('一圈油钱固定','调度员的目标：座位不空（continuous batching）'),('人数 × 行李 ≤ 座位','每圈的准入条件；满了请人下车（抢占）'),
('新车出库 1–2 分钟','准入控制 + 预热车队，别指望临时出车'),('按箱寄存，前箱一变后箱全废','常客上同一辆车（cache-aware 路由）'),('寄存只省搬不省跑','命中率高 ≠ 吞吐高，吞吐看坐几人')]
card('08-调度员约束表',1560,f'''{EYE}<h1>三篇合起来，<br>是调度员的约束表</h1><div class="sub">左边是三篇算出来的事实，右边是引擎每一圈要遵守的规则。Phase 1 学的就是右边。</div>
<div class="card" style="padding:6px 38px">'''+''.join(f'''<div style="display:grid;grid-template-columns:1fr 60px 1.2fr;align-items:center;padding:22px 0;border-bottom:2px solid #eee8dc;font-size:26px"><div style="font-weight:700">{a}</div><div style="color:#c4763a;text-align:center;font-size:30px">→</div><div style="color:#2a2620;line-height:1.4">{b}</div></div>''' for a,b in crow)+'''</div>
<div class="callout">三篇算的是「跑一圈多少钱、坐几人、寄存省多少」；调度员管的是<b>「每一圈让谁上、谁下、谁先搬」</b>。</div>''')
