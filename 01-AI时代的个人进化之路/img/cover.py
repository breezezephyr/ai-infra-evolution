import subprocess, pathlib, sys
D=pathlib.Path(__file__).parent
PHASES=[('0','热身','#9AA7B5'),('1','心智模型','#5FA8D3'),('2','动手压测','#E0A458'),('3','架构翻译','#7BC47F'),('3b','容量·缓存·合规','#C98BDB'),('4','实时多模态','#E06C75'),('5','实战','#F2D479')]
def cover(name, kicker, big, title, sub, active=None, hue='#14202C', accent='#E0A458'):
    nodes=''
    xs=[70,255,440,625,810,995,1180]
    for (n,t,c),x in zip(PHASES,xs):
        on = active is None or active==n
        dim = 1 if on else .28
        nodes+=f'''<g opacity="{dim}"><circle cx="{x}" cy="470" r="{14 if active==n else 9}" fill="{c}" stroke="{hue}" stroke-width="4"/>
        <text x="{x}" y="512" text-anchor="middle" font-size="15" font-weight="700" fill="{c}" font-family="Menlo,monospace">{n}</text>
        <text x="{x}" y="534" text-anchor="middle" font-size="14" fill="#C9D3DD" font-family="PingFang SC">{t}</text></g>'''
    if active:
        ax=xs[[p[0] for p in PHASES].index(active)]
        nodes+=f'<circle cx="{ax}" cy="470" r="26" fill="none" stroke="{accent}" stroke-width="2" opacity=".7"/>'
    html=f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:1280px;height:545px;overflow:hidden;background:{hue};font-family:"PingFang SC","Hiragino Sans GB",sans-serif}}
canvas{{position:absolute;inset:0}}
.card{{position:absolute;left:400px;top:0;width:480px;height:545px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:0 26px;color:#F3F0E8}}
.kick{{font:15px Menlo,monospace;letter-spacing:.14em;color:#9AA7B5;display:flex;align-items:center;gap:10px}}
.kick::before,.kick::after{{content:"";width:28px;height:1px;background:#9AA7B5}}
.big{{font-size:78px;font-weight:800;line-height:1;margin-top:22px;color:{accent};letter-spacing:-.02em}}
.title{{font-size:34px;font-weight:800;line-height:1.3;margin-top:18px}}
.sub{{font-size:17px;color:#C9D3DD;margin-top:14px;line-height:1.5}}
svg{{position:absolute;left:0;top:0}}
</style></head><body>
<canvas id="c" width="2560" height="1090" style="width:1280px;height:545px"></canvas>
<svg width="1280" height="545" viewBox="0 0 1280 545">
<path d="M70 470 C 160 470, 180 470, 255 470 S 360 470, 440 470 S 545 470, 625 470 S 730 470, 810 470 S 915 470, 995 470 S 1100 470, 1180 470" stroke="#3A4A5C" stroke-width="3" fill="none" stroke-dasharray="6 8"/>
{nodes}</svg>
<div class="card"><div class="kick">{kicker}</div><div class="big">{big}</div><div class="title">{title}</div><div class="sub">{sub}</div></div>
<script>
const c=document.getElementById('c'),g=c.getContext('2d');g.scale(2,2);
// contour lines: layered noisy ellipses around two centers
function rnd(s){{return function(){{s=(s*16807)%2147483647;return (s-1)/2147483646}}}}
const R=rnd(20260916);
g.strokeStyle='rgba(255,255,255,0.07)';g.lineWidth=1.2;
for(const [cx,cy] of [[180,120],[1120,400],[640,560]]){{
  for(let k=1;k<=14;k++){{g.beginPath();
    for(let a=0;a<=Math.PI*2+0.01;a+=0.05){{const r=k*34+Math.sin(a*3+k)*10+Math.cos(a*5-k*.7)*7;
      const x=cx+Math.cos(a)*r*1.4,y=cy+Math.sin(a)*r*.75; a==0?g.moveTo(x,y):g.lineTo(x,y)}}
    g.stroke()}}}}
// grid ticks
g.fillStyle='rgba(255,255,255,0.05)';for(let x=0;x<1280;x+=40)for(let y=0;y<545;y+=40)g.fillRect(x,y,1,1);
</script></body></html>'''
    p=(pathlib.Path(name+'.html') if name.startswith('/') else D/f'{name}.html'); p.write_text(html)
    subprocess.run(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=2','--window-size=1280,545',f'--screenshot={p.with_suffix(".png")}',f'file://{p}'],capture_output=True)
    print(name)

# 引导篇：整条路线全亮
cover('00-封面','进化之路 · 引导','7 站','一次对话的考古：<br>从 FlashMLA 到在线架构','先看整张地图，再找自己已经站着的位置',active=None,hue='#14202C',accent='#E0A458')
# 子风格示例：Phase 2
cover('00-封面-phase2示例','进化之路 · P2','5–8 周','把概念变成<br>面板上的曲线','vLLM · Grafana · 三组压测',active='2',hue='#1C1A12',accent='#E0A458')
cover('02-Phase0-一辆公交车讲完三篇的账/img/00-封面','进化之路 · P0','1 辆车','一辆公交车，<br>讲完推理成本的三篇账','跑圈 · 搬行李 · 座位 · 坐几人 · 寄存行李',active='0',hue='#171B20',accent='#9AA7B5')
cover('03-Phase1上-调度员每一圈做的四个决定/img/00-封面','进化之路 · P1 · 上','4 个决定','调度员每一圈<br>做的四个决定','谁继续坐 · 谁上来 · 谁下车 · 这圈怎么开',active='1',hue='#121C26',accent='#5FA8D3')
cover('04-Phase1下-行李架的账本与跟班/img/00-封面','进化之路 · P1 · 下','16 格','行李架的账本<br>与跟班','格子 · 清单 · 共用 · 先猜再验 · 一张图',active='1',hue='#121C26',accent='#5FA8D3')
cover('00-封面-phase4示例','进化之路 · P4','800 ms','一次语音回合的<br>延迟预算','VAD · ASR · 首 token · TTS · 网络',active='4',hue='#221418',accent='#E06C75')
cover('05-Phase2上-把一辆车开起来/img/00-封面','进化之路 · P2 · 上','1 张卡','把一辆车开起来：<br>面板与第一组压测','8 GB · Qwen3-1.7B · 六行面板 · 坐几人',active='2',hue='#1C1A12',accent='#E0A458')
cover('06-Phase2下-拨那个参数/img/00-封面','进化之路 · P2 · 下','4 个旋钮','拨那个参数：<br>预算、常客、抢占','行李多重 · 寄存 · 座位砍半 · 两面对上',active='2',hue='#1C1A12',accent='#E0A458')
cover('11-Phase3b·1-出一辆新车要多久/img/00-封面','进化之路 · P3b · 1','24 秒','车库：出一辆新车<br>要多久','冷启动 · 扩容信号 · 排空 · 多机房',active='3b',hue='#1A1420',accent='#C98BDB')
cover('12-Phase3b·2-不上车的答案/img/00-封面','进化之路 · P3b · 2','0.88','不上车的答案：<br>语义缓存','同义问法 · 换一个词 · 谁不该进',active='3b',hue='#1A1420',accent='#C98BDB')
