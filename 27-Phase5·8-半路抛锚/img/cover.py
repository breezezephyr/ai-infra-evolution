"""Phase 5.8 cover, copied from Phase 5.2's seven-stop series template."""
import sys
sys.dont_write_bytecode = True
from render import render

PHASES = [
    ('0', '热身', '#9AA7B5'), ('1', '心智模型', '#5FA8D3'),
    ('2', '动手压测', '#E0A458'), ('3', '架构翻译', '#7BC47F'),
    ('3b', '容量·缓存·合规', '#C98BDB'), ('4', '实时多模态', '#E06C75'),
    ('5', '实战', '#F2D479'),
]


def cover():
    hue, accent = '#201E16', '#F2D479'
    nodes = ''
    for (number, title, color), x in zip(PHASES, [70, 255, 440, 625, 810, 995, 1180]):
        active = number == '5'
        nodes += f'''<g opacity="{1 if active else .28}">
        <circle cx="{x}" cy="470" r="{14 if active else 9}" fill="{color}" stroke="{hue}" stroke-width="4"/>
        <text x="{x}" y="512" text-anchor="middle" font-size="15" font-weight="700" fill="{color}" font-family="Menlo,monospace">{number}</text>
        <text x="{x}" y="534" text-anchor="middle" font-size="14" fill="#C9D3DD" font-family="PingFang SC">{title}</text></g>'''
    nodes += f'<circle cx="1180" cy="470" r="26" fill="none" stroke="{accent}" stroke-width="2" opacity=".7"/>'
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>进化之路P5·8｜半路抛锚：取消、排空与安全重试</title><style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    html,body{{width:1280px;height:545px;overflow:hidden;background:{hue};font-family:"PingFang SC","Hiragino Sans GB",sans-serif;-webkit-font-smoothing:antialiased}}
    canvas{{position:absolute;inset:0}}
    .card{{position:absolute;left:400px;top:0;width:480px;height:545px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:0 26px;color:#F3F0E8}}
    .kick{{font:15px Menlo,"PingFang SC",monospace;letter-spacing:.14em;color:#9AA7B5;display:flex;align-items:center;gap:10px;white-space:nowrap}}
    .kick::before,.kick::after{{content:"";width:28px;height:1px;background:#9AA7B5}}
    .big{{font-size:62px;font-weight:800;line-height:1.4;margin-top:22px;color:{accent};letter-spacing:-.02em}}
    .title{{font-size:28px;font-weight:800;line-height:1.3;margin-top:18px;white-space:nowrap}}
    .sub{{font-size:17px;color:#C9D3DD;margin-top:14px;line-height:1.5}}
    svg{{position:absolute;left:0;top:0}}
    </style></head><body>
    <canvas id="c" width="2560" height="1090" style="width:1280px;height:545px"></canvas>
    <svg width="1280" height="545" viewBox="0 0 1280 545">
    <path d="M70 470 C160 470,180 470,255 470 S360 470,440 470 S545 470,625 470 S730 470,810 470 S915 470,995 470 S1100 470,1180 470" stroke="#3A4A5C" stroke-width="3" fill="none" stroke-dasharray="6 8"/>
    {nodes}</svg>
    <div class="card"><div class="kick">进化之路 · P5 · 8</div><div class="big">半路抛锚</div>
    <div class="title">取消、排空与安全重试</div></div>
    <script>
    const c=document.getElementById('c'),g=c.getContext('2d');g.scale(2,2);
    g.strokeStyle='rgba(255,255,255,0.07)';g.lineWidth=1.2;
    for(const [cx,cy] of [[180,120],[1120,400],[640,560]]){{
      for(let k=1;k<=14;k++){{g.beginPath();
        for(let a=0;a<=Math.PI*2+.01;a+=.05){{
          const r=k*34+Math.sin(a*3+k)*10+Math.cos(a*5-k*.7)*7;
          const x=cx+Math.cos(a)*r*1.4,y=cy+Math.sin(a)*r*.75;
          a===0?g.moveTo(x,y):g.lineTo(x,y);
        }}g.stroke();
      }}
    }}
    g.fillStyle='rgba(255,255,255,0.05)';
    for(let x=0;x<1280;x+=40)for(let y=0;y<545;y+=40)g.fillRect(x,y,1,1);
    </script></body></html>'''
    render('00-封面', html, 1280, 545)


if __name__ == '__main__':
    cover()

