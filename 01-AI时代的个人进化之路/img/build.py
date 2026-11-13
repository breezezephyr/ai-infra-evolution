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
def card(name, h, body, extra_css=''):
    html=f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{extra_css}html,body{{height:{h}px}}</style></head><body>{body}</body></html>'
    p=D/f'{name}.html'; p.write_text(html)
    subprocess.run(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=2',f'--window-size=1080,{h}',f'--screenshot={D}/{name}.png',f'file://{p}'],capture_output=True)
    print(name)

EYE='<div class="eyebrow">进化之路 · 引导</div>'

# 01 四层地图
layers=[('应用 / Agent','把模型能力包成用户愿意付钱的东西','我们过去两年在这里',True,'#eee8dc','#1c1a17'),
        ('在线服务架构','让海量请求稳定、便宜地被接住：路由、限流、扩缩容、缓存、可观测','这次找到的接入点',True,'#2f5f8a','#fff'),
        ('训练 / 推理框架','让一个模型在一台机器上跑得快：vLLM、Megatron','',False,'#e6e0d4','#1c1a17'),
        ('算子 / 硬件适配','让一次矩阵乘法跑得更快：CUDA kernel、FlashMLA','起点，先放着',False,'#c4763a','#fff')]
rows=''.join(f'''<div style="display:flex;gap:26px;align-items:stretch;margin-bottom:18px">
<div style="flex:1;background:{bg};color:{fg};border-radius:18px;padding:30px 34px">
<div style="font-size:38px;font-weight:800">{t}</div><div style="font-size:26px;margin-top:8px;opacity:.85;line-height:1.45">{d}</div></div>
<div style="width:250px;display:flex;align-items:center;font-size:26px;line-height:1.4;font-weight:600">{'<span style=color:#c4763a>'+m+'</span>' if m=='起点，先放着' else '<span style=color:#2f5f8a>'+m+'</span>' if m else ''}</div></div>''' for t,d,m,_,bg,fg in layers)
card('01-四层地图',1640,f'''{EYE}<h1>大模型公司的<br>四层技术团队</h1><div class="sub">一个热门项目容易让人以为那就是全部。地图摊开，它是最底下的一个区域。</div>
<div style="margin-top:48px">{rows}</div>
<div class="callout">往下一层不需要重学：<b>我们已经站在最上层，接入点就在隔壁。</b></div>
<div class="note">分层是简化口径；训练 Infra 与推理 Infra 在多数公司是两个团队，这里合并显示。</div>''')

# 02 两条路
card('02-两条路对比',1560,f'''{EYE}<h1>AI Infra 的<br>两条路</h1><div class="sub">都是 Infra，吃的能力不一样。</div>
<div class="card" style="padding:0;overflow:hidden">
<div style="display:grid;grid-template-columns:230px 1fr 1fr;font-size:27px">
<div style="padding:26px 30px;background:#f3eee3"></div>
<div style="padding:26px 30px;background:#c4763a;color:#fff;font-weight:800;font-size:30px">算子开发</div>
<div style="padding:26px 30px;background:#2f5f8a;color:#fff;font-weight:800;font-size:30px">推理服务化</div>
''' + ''.join(f'''<div style="padding:26px 30px;border-top:2px solid #eee8dc;color:#6f695f;font-weight:600">{k}</div>
<div style="padding:26px 30px;border-top:2px solid #eee8dc;line-height:1.45" class="{'strike' if s else ''}">{a}</div>
<div style="padding:26px 30px;border-top:2px solid #eee8dc;line-height:1.45;font-weight:400" class="">{b}</div>''' for k,a,b,s in [
('解决什么','一次矩阵乘法跑得更快','海量请求稳定、便宜地被接住',False),
('数学 / 数据天赋','重：数值等价变换、roofline 直觉','轻：会算容量和成本账',False),
('硬件理解','重：显存层级、warp、Tensor Core','中：prefill / decode 各卡在哪',False),
('工程能力','CUDA、模板元编程、profiling','分布式、K8s、限流熔断、可观测',False),
('业务感知','少','多：SLA、成本归因、灰度评测',False)]) + '''</div></div>
<div class="callout">算子开发吃数学和硬件天赋，推理服务化吃分布式工程和业务感。<b>我们的存量在右边那一列。</b></div>''')

# 03 旧问题新约束
pairs=[('限流','计量单位从 QPS 变成 token，输出长度事先不知道'),
('负载均衡','prefix cache 是实例本地的，打错实例就丢'),
('优雅下线','实例上挂的不是连接池，是显存里的 KV cache'),
('扩缩容','新实例要加载几十 GB 权重，分钟级'),
('灰度发布','接口 200 但回答变差——做过 Agent 评测的人有工具')]
rows=''.join(f'''<div style="display:grid;grid-template-columns:230px 60px 1fr;align-items:center;padding:28px 0;border-bottom:2px solid #eee8dc">
<div style="font-size:34px;font-weight:800">{a}</div><div style="color:#c4763a;font-size:34px;text-align:center">+</div><div style="font-size:28px;line-height:1.45;color:#2a2620">{b}</div></div>''' for a,b in pairs)
card('03-旧问题新约束',1420,f'''{EYE}<h1>旧问题 + 新约束</h1><div class="sub">这一层的知识结构。左边是做过的，右边是多出来的那一个条件。</div>
<div class="card" style="padding:6px 38px">{rows}</div>
<div class="callout">街道布局是老家的，<b>路牌换了语言</b>。</div>''')

# 04 新概念旧锚点
pairs=[('KV cache','随对话增长的显存租约','手动维护的 messages 数组'),
('Continuous batching','每步 decode 间动态换人','攒批'),
('PagedAttention','block table 逻辑块→物理块','操作系统页表'),
('抢占','显存满了踢谁','任务队列、状态机'),
('Cache-aware 路由','相同前缀落同一实例','轮询 / 最少连接'),
('实时会话','有状态长连接绑 GPU','WebSocket 网关')]
rows=''.join(f'''<div style="display:grid;grid-template-columns:1fr 70px 300px;align-items:center;padding:24px 0;border-bottom:2px solid #eee8dc">
<div><div style="font-size:30px;font-weight:800" class="mono">{a}</div><div style="font-size:24px;color:#6f695f;margin-top:4px">{d}</div></div>
<div style="color:#9a9386;font-size:30px;text-align:center">←</div>
<div style="font-size:28px;font-weight:600;color:#2f5f8a;line-height:1.4">{b}</div></div>''' for a,d,b in pairs)
card('04-新概念旧锚点',1500,f'''{EYE}<h1>每个新概念，<br>先找旧锚点</h1><div class="sub">学习路线的设计原则。有锚点的概念学起来是修正，不是记忆。</div>
<div class="card" style="padding:6px 38px">{rows}</div>
<div style="display:flex;gap:22px;margin-top:40px;font-size:26px;color:#6f695f"><span class="mono" style="color:#1c1a17">左</span>要去的地方的语言<span class="mono" style="color:#2f5f8a;margin-left:30px">右</span>已经会的语言</div>''')

# 05 系列文章
pop=['为什么 AI 说话，是一个字一个字蹦出来的？','为什么 AI 收费，要把「你说的」和「它说的」分开算？','一块显卡装不下一个 AI，怎么办？','搬一个数字，够算 457 次乘法','想让 AI 回得快一点，为什么要多花三倍钱？']
tech=['LLM Cost 为什么要分三档？从推理硬件讲起','KV cache、decode batch，和容量规划该盯的变量','cached token 到底省了什么','fast 档的溢价买的是什么，以及预留容量的陷阱','一张图、一秒音频、一秒视频，各值多少 token']
def lst(items,color):
    return ''.join(f'<div style="display:flex;gap:18px;padding:16px 0;border-bottom:2px solid #eee8dc;font-size:26px;line-height:1.4"><span class="mono" style="color:{color};font-weight:700;flex:none">0{i+1}</span><span>{t}</span></div>' for i,t in enumerate(items))
card('05-已有的积累',1400,f'''{EYE}<h1>已经站着的位置</h1><div class="sub">8 月写的技术版五篇，约 40,000 字，36 张图。这次路线的第一阶段，大半在这里。</div>
<div class="card" style="padding:28px 34px"><div style="font-size:26px;color:#2f5f8a;font-weight:700;letter-spacing:.06em" class="mono">技术版 · AI 推理的成本结构</div><div style="font-size:23px;color:#9a9386;margin:6px 0 10px">给架构师，每个数字标来源</div>{lst(tech,'#2f5f8a').replace('font-size:26px','font-size:29px').replace('padding:16px 0','padding:22px 0')}</div>
<div class="callout">它们回答的是<b>每一步花多少钱</b>。这次要补的是<b>引擎每一步怎么决定让谁上</b>。</div>
<div class="note">五篇链接见文末。</div>''')

# 06 路线
ph=[('0','热身','1','「调用方现象 → 提供方机制」对照表'),
('1','心智模型','2–4','请求生命周期图，节点标 vLLM 指标名'),
('2','动手压测','5–8','vLLM + Grafana 面板，三组压测曲线'),
('3','架构翻译','9–12','六份一页纸设计文档'),
('3b','容量·缓存·合规','13–15','十份'),
('4','实时多模态','16–21','语音 demo，回合延迟预算表填实测数字'),
('5','实战','持续','在现有岗位接下模型网关层')]
rows=''.join(f'''<div style="display:grid;grid-template-columns:90px 300px 130px 1fr;align-items:center;padding:22px 0;border-bottom:2px solid #eee8dc;font-size:27px">
<div class="mono" style="font-weight:800;color:{'#c4763a' if n=='4' else '#2f5f8a'}">{n}</div><div style="font-weight:700">{t}</div><div class="mono gray">{w}{'' if w=='持续' else ' 周'}</div><div style="color:#2a2620;line-height:1.4">{o}</div></div>''' for n,t,w,o in ph)
card('06-路线骨架',1440,f'''{EYE}<h1>21 周的骨架</h1><div class="sub">每周约 10 小时。详细任务在看板上，会随进度改。</div>
<div class="card" style="padding:6px 38px">{rows}</div>
<div class="callout">每个阶段的产出物都是一份可以贴出来的东西，<b>不是「学完了」</b>。</div>''')

# 00 封面 1280x545
cov=f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:1280px;height:545px;background:#f8f5ee;font-family:"PingFang SC","Hiragino Sans GB",sans-serif;overflow:hidden}}
.stripes{{position:absolute;left:0;right:0;height:88px;background:repeating-linear-gradient(90deg,var(--c) 0 14px,transparent 14px 28px)}}
.box{{position:absolute;left:400px;top:46px;width:480px;height:453px;background:#fbf9f4;border-radius:14px;box-shadow:0 4px 18px rgba(0,0,0,.08);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:30px}}
</style></head><body>
<div class="stripes" style="--c:#2f5f8a;top:70px"></div><div class="stripes" style="--c:#c4763a;top:228px"></div><div class="stripes" style="--c:#a84d3a;top:386px"></div>
<div class="box"><div style="display:flex;align-items:center;gap:10px;color:#8a8378;font-size:17px;font-family:Menlo,monospace"><span style="width:22px;height:4px;background:#2f5f8a;display:inline-block"></span>个人进化 · 01</div>
<div style="font-size:64px;font-weight:800;color:#c4763a;margin-top:26px;line-height:1">11 问</div>
<div style="font-size:20px;color:#6f695f;margin-top:10px">从一个 GitHub 链接<br>到一个新的接入点</div>
<div style="font-size:34px;font-weight:800;line-height:1.25;margin-top:26px;color:#1c1a17">一次对话的考古：<br>从 FlashMLA 到在线架构</div>
<div style="width:380px;height:2px;background:#e6e0d4;margin:18px 0 14px"></div>
<div style="font-size:19px;font-weight:700;color:#1c1a17">先看地图，再找自己已经站着的位置</div></div></body></html>'''
p=D/'00-封面.html'; p.write_text(cov)
subprocess.run(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=2','--window-size=1280,545',f'--screenshot={D}/00-封面.png',f'file://{p}'],capture_output=True); print('00-封面')
