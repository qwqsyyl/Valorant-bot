"""Local-only history artwork from the public history model; no network or credentials."""
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from .errors import ShopCheckError
from .card_backgrounds import load_background, card_opacity

ASSETS = Path(__file__).parent / 'assets'
ZONE = ZoneInfo('Asia/Shanghai')
COLORS = {'胜利': '#83E4CB', '失败': '#FF9EAC', '平局': '#CCD0DE'}


def text_label(value, fallback='未知'):
    return ' '.join(value.split())[:100] if isinstance(value, str) and value.strip() else fallback


def render_card(history):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    rows = tuple(history.matches)
    if not 1 <= len(rows) <= 5:
        raise ShopCheckError('战绩卡片仅接受一至五场对局')
    fonts = [os.environ.get('VALORANT_CARD_FONT', ''),
             '/usr/share/fonts/truetype/arphic/uming.ttc',
             '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
             '/System/Library/Fonts/Supplemental/Songti.ttc']
    font = next((p for p in fonts if p and Path(p).is_file()), None)
    if not font:
        raise ShopCheckError('未配置中文字体')
    numbers = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf') if Path(p).is_file()), font)
    def face(size, numeric=False):
        return ImageFont.truetype(numbers if numeric else font, size)
    def fit(value, size, width, minimum=22, numeric=False):
        value = text_label(value)
        while size > minimum and face(size, numeric).getlength(value) > width:
            size -= 1
        chosen = face(size, numeric)
        while value and chosen.getlength(value) > width:
            value = value[:-2] + '…' if len(value) > 1 else ''
        return value, chosen
    name = text_label(history.display_name, '端游角色')
    name_size = 46
    while name_size > 28 and face(name_size).getlength(name) > 1088:
        name_size -= 1
    name_lines, current = [], ''
    for char in name:
        if current and face(name_size).getlength(current+char) > 1088:
            name_lines.append(current);current = ''
        current += char
    if current:
        name_lines.append(current)
    if len(name_lines) > 2:
        name_lines = [name_lines[0],fit(''.join(name_lines[1:]),name_size,1088,name_size)[0]]
    extra = (len(name_lines)-1)*42
    top = 458+extra
    width, height = 1200, max(808, top+(len(rows)-1)*218+198+152)
    image = load_background('history', (width, height), centering=(0.75, 0.22), color='#141929')
    overlay = Image.new('RGBA',image.size)
    draw = ImageDraw.Draw(overlay)
    for y in range(height):
        draw.line((0,y,width,y),fill=(8,12,26,int(115+55*y/height)))
    image = Image.alpha_composite(image,overlay)
    white, muted = '#F4F2F8','#B1B6CB'
    def text(x,y,value,size=32,color=white,align='left',numeric=False,max_width=None):
        value = text_label(value)
        value, chosen = fit(value,size,max_width,22,numeric) if max_width else (value,face(size,numeric))
        length = chosen.getlength(value)
        if align == 'center':
            x -= length/2
        elif align == 'right':
            x -= length
        ImageDraw.Draw(image).text((x,y),value,font=chosen,fill=color,
            stroke_width=1 if chosen.size >= 36 else 0,stroke_fill=(10,12,28,100))
    def panel(box,fill,outline=None,radius=20):
        nonlocal image
        layer = Image.new('RGBA',image.size)
        ImageDraw.Draw(layer).rounded_rectangle(box,radius=radius,fill=fill,outline=outline,width=1)
        image = Image.alpha_composite(image,layer)
    ImageDraw.Draw(image).line((56,48,126,48),fill='#D0B8EE',width=4)
    text(56,69,'VALORANT  /  MATCH HISTORY',22,muted,numeric=True)
    panel((972,53,1144,103),(22,28,44,200),(172,182,209,90),16)
    text(1058,63,'国服端游',28,align='center')
    text(52,112,'最近战绩',82)
    for i,line in enumerate(name_lines):
        text(56,228+i*42,line,name_size)
    text(58,295+extra,f'最近 {len(rows)} 场已结束对局',28,muted)
    panel((48,354+extra,1152,428+extra),(15,24,38,182),(180,183,215,72),18)
    counts = [('胜利','胜'),('失败','负'),('平局','平')]
    x = 74
    for result, short in counts:
        count = sum(row.result == result for row in rows)
        if count or result in {'胜利','失败'}:
            label = f'{count} {short}'
            text(x,364+extra,label,42,COLORS[result]);x += face(42).getlength(label)+54
    other = sum(row.result not in COLORS for row in rows)
    if other:
        text(x,370+extra,f'{other} 其他',32,muted)
    for i,row in enumerate(rows):
        panel((858+i*51,378+extra,893+i*51,401+extra),COLORS.get(row.result,'#CCD0DE'),None,7)
    try:
        icons = json.loads((ASSETS/'history-agents/index.json').read_text())['agents']
    except (OSError,ValueError,KeyError,TypeError):
        icons = {}
    alpha = card_opacity('VALORANT_HISTORY_PANEL_ALPHA',218)
    fetched = datetime.fromtimestamp(history.fetched_at,ZONE)
    for i,row in enumerate(rows):
        y = top+i*218
        color = COLORS.get(row.result,'#CCD0DE')
        panel((48,y,1152,y+198),(11,18,34,alpha),(195,189,219,70),22)
        panel((48,y+20,54,y+178),color,None,3)
        panel((76,y+29,216,y+169),(49,65,77,180),(195,205,224,65),16)
        entry = icons.get(row.agent,{})
        filename = entry.get('file') if isinstance(entry,dict) else None
        drawn = False
        if isinstance(filename,str) and Path(filename).name == filename:
            try:
                with Image.open(ASSETS/'history-agents'/filename) as source:
                    if source.width*source.height <= 1_048_576:
                        avatar = ImageOps.contain(source.convert('RGBA'),(138,138),Image.Resampling.LANCZOS)
                        image.alpha_composite(avatar,(77+(138-avatar.width)//2,y+30+(138-avatar.height)//2))
                        drawn = True
            except (OSError,ValueError,Image.DecompressionBombError):
                pass
        if not drawn:
            text(146,y+71,row.agent,34,align='center',max_width=128)
        text(244,y+25,row.agent,44,max_width=390)
        text(244,y+88,f'{text_label(row.mode)} · {text_label(row.map_name)}',29,'#D0D3E1',max_width=408)
        if row.played_at is not None:
            played = datetime.fromtimestamp(row.played_at,ZONE)
            date = played.strftime('%m-%d %H:%M' if played.year == fetched.year else '%Y-%m-%d %H:%M')
        else:
            date = '时间未知'
        text(244,y+142,date,27,muted,max_width=408)
        fill = (32,75,71,210) if row.result == '胜利' else (89,42,58,210) if row.result == '失败' else (51,57,75,210)
        panel((674,y+24,784,y+65),fill,None,12)
        text(729,y+28,row.result,29,color,align='center',max_width=102)
        number = lambda value: '?' if value is None else str(value)
        text(729,y+75,f'{number(row.own_score)} : {number(row.opponent_score)}',48,align='center',numeric=True,max_width=230)
        text(729,y+143,'比分',26,muted,align='center')
        text(1007,y+75,' / '.join(number(v) for v in (row.kills,row.deaths,row.assists)),41,align='center',numeric=True,max_width=270)
        text(1007,y+143,'K / D / A',24,muted,align='center',numeric=True)
    ImageDraw.Draw(image).line((56,height-93,1144,height-93),fill=(190,186,211,90),width=1)
    text(56,height-73,'数据采集于 '+fetched.strftime('%Y-%m-%d %H:%M')+' · 北京时间',26,muted,max_width=980)
    text(1144,height-70,'瓦 bot',25,'#D0B8EE',align='right')
    output = BytesIO()
    image.convert('RGB').save(output,format='JPEG',quality=90,optimize=True)
    return output.getvalue()
