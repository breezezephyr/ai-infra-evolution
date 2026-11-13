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
.callout{background:#fbf1e6;border:2px solid #f0dcc4;border-radius:18px;padding:32px 36px;font-size:32px;line-height:1.6;margin-top:40px;color:#2a2620}
.callout b{color:#1c1a17}
.note{color:#9a9386;font-size:24px;margin-top:28px;padding-top:0;line-height:1.5}
.orange{color:#c4763a}.green{color:#4f7a52}.gray{color:#9a9386}
.strike{text-decoration:line-through;text-decoration-thickness:4px;text-decoration-color:#a84d3a;color:#9a9386}
'''
CSS += """
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:40px}
.box{background:#fff;border:2px solid #e6e0d4;border-radius:22px;padding:30px 32px}
.box h3{font-size:34px;font-weight:800}
.box .cap{font-size:24px;color:#6f695f;line-height:1.5;margin-top:10px}
.box .big{font-size:64px;font-weight:800;line-height:1.1;margin-top:8px;letter-spacing:-.02em}
.one{display:grid;grid-template-columns:170px 1fr;gap:0;margin-top:40px;background:#fff;border:2px solid #e6e0d4;border-radius:22px;overflow:hidden}
.one>div{padding:26px 30px;border-bottom:2px solid #eee8dc;font-size:29px;line-height:1.55}
.one>.h{background:#f3eee3;font-weight:800;color:#6f695f;font-size:27px}
.one>div:nth-last-child(-n+2){border-bottom:0}
"""
EYE='进化之路 · P3b·2'

def card(name, h, body):
    html=f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}html,body{{height:{h}px}}</style></head><body>{body}</body></html>'
    p=D/f'{name}.html'; p.write_text(html)
    subprocess.run(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=2',f'--window-size=1080,{h}',f'--screenshot={D}/{name}.png',f'file://{p}'],capture_output=True)
    print(name, h)

card("01-一页纸",1860,f"""
<div class="eyebrow">{EYE}</div>
<h1>不上车的答案：<br>语义缓存</h1>
<div class="sub">一页纸 · 问法够像，就交旧答案，这趟车不用开</div>
<div class="one">
 <div class="h">老做法</div><div>字符串相等才回缓存<br>问法差一个字，就当没见过</div>
 <div class="h">哪里失效</div><div>五种问法在 θ = 0.88 对上 <b class="orange">93%</b>，答错为 0<br>只换一个区分词，同一阈值仍有 <b class="orange">31%</b> 答错</div>
 <div class="h">新方案</div><div>嵌入后取最近的原问，≥ θ 才回旧答案<br>同义问法用 0.88。差一个词就反的，不进这层<br>记忆、个性化、会过期的，一律不进<br><span class="strike">字符串相等才算命中</span>　<span class="strike">一个阈值通吃</span></div>
 <div class="h">怎么验</div><div>同义改写看命中率，换一词看答错率<br><span class="gray">不成立：答错压到 0 时，同义命中掉到两成</span></div>
</div>
<div class="grid3">
 <div class="box"><h3>同义 · 0.88</h3><div class="big green">93%</div><div class="cap">命中<br>答错为 0</div></div>
 <div class="box"><h3>换一词 · 0.88</h3><div class="big">31%</div><div class="cap">仍然答错<br>22 / 72</div></div>
 <div class="box"><h3>嵌入</h3><div class="big">15 ms</div><div class="cap">热单条 p50<br>整段旧答案</div></div>
</div>
<div class="callout"><b>同义问法不用上车。</b><br>便宜/贵、记名/不记名，嵌入还停在原句。把 θ 拧到 0.98 才挡得住，同义命中会掉到 20%。</div>
<div class="note">Qwen3-Embedding-0.6B · 100 条原问 · 427 句同义改写 · 72 条只换一个区分词</div>
""")
