"""Card presentation accepts public shop models only, never credentials."""
from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from .errors import ShopCheckError
from .shop_backgrounds import choose_background, card_opacity


def shop_text(shop, display_name):
    lines = [f'{display_name} · 每日商店']
    lines += [f'{offer.name} · {offer.price} VP' for offer in shop.offers]
    lines += ['数据更新于：' + datetime.fromtimestamp(shop.fetched_at, ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H:%M') + '（北京时间）']
    return '\n'.join(lines)


def render_card(shop, display_name, images=None):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    images = images or {}
    # Preserve the previous appearance unless the random pool is enabled.
    enabled = bool(os.environ.get('VALORANT_CARD_BACKGROUND_DIR'))
    panel_alpha = card_opacity('VALORANT_CARD_PANEL_ALPHA', 96 if enabled else 206)
    weapon_alpha = card_opacity('VALORANT_CARD_WEAPON_ALPHA', 56 if enabled else 228)
    text_style = dict(stroke_width=2, stroke_fill='#171226') if enabled else {}
    candidates = [os.environ.get('VALORANT_CARD_FONT', ''),
                  '/usr/share/fonts/truetype/arphic/uming.ttc',
                  '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
                  '/System/Library/Fonts/Supplemental/Songti.ttc']
    font_path = next((path for path in candidates if path and Path(path).is_file()), None)
    if font_path is None:
        raise ShopCheckError('未配置中文字体，本次发送文字商店')
    title = ImageFont.truetype(font_path, 66)
    name_font = ImageFont.truetype(font_path, 35)
    price_font = ImageFont.truetype(font_path, 38)
    small = ImageFont.truetype(font_path, 25)

    def wrap(text, face, width):
        lines, current = [], ''
        for char in text:
            if current and face.getlength(current + char) > width:
                lines.append(current)
                current = ''
            current += char
        return lines + ([current] if current else [])

    account_lines = wrap(display_name, name_font, 1000)
    top = 160 + 45 * len(account_lines)
    cell_width, gap = 502, 24
    names = [wrap(offer.name, name_font, cell_width - 56) for offer in shop.offers]
    row_heights = [max(350, 305 + 42 * max(len(line) for line in names[i:i+2]))
                   for i in range(0, len(names), 2)]
    footer_y = top + sum(row_heights) + gap * max(0, len(row_heights) - 1) + 28
    width, height = 1800, max(1040, footer_y + 72)
    default = Path(os.environ.get('VALORANT_CARD_BACKGROUND') or
                   Path(__file__).parent / 'assets' / 'shop-background-v1.png')
    background = choose_background(default)
    image = None
    for path in dict.fromkeys((background, default)):
        try:
            with Image.open(path) as source:
                image = ImageOps.fit(source.convert('RGB'), (width, height),
                                     method=Image.Resampling.LANCZOS, centering=(0.85, 0.3)).convert('RGBA')
            break
        except (OSError, ValueError, Image.DecompressionBombError):
            continue
    if image is None:
        image = Image.new('RGBA', (width, height), '#171226')
    scrim = Image.new('RGBA', (width, 1))
    scrim.putdata([(14, 10, 30, int(100 * max(0, 1 - x / 1300))) for x in range(width)])
    image = Image.alpha_composite(image, scrim.resize((width, height)))
    draw = ImageDraw.Draw(image)
    draw.line((60, 44, 124, 44), fill='#ddb1e7', width=3)
    draw.text((60, 58), '每日商店', font=title, fill='#fff5fc', **text_style)
    for index, line in enumerate(account_lines):
        draw.text((62, 140 + index * 45), line, font=name_font, fill='#e8c8ec', **text_style)

    y = top
    for row_index, row_height in enumerate(row_heights):
        for column in range(2):
            index = row_index * 2 + column
            if index >= len(shop.offers):
                break
            offer = shop.offers[index]
            x = 54 + column * (cell_width + gap)
            layer = Image.new('RGBA', image.size)
            panel = ImageDraw.Draw(layer)
            panel.rounded_rectangle((x, y, x + cell_width, y + row_height), radius=22,
                                    fill=(18, 13, 34, panel_alpha), outline=(218, 180, 238, 94), width=1)
            # Slightly lighter image stage makes dark weapon finishes visible.
            panel.rounded_rectangle((x + 16, y + 44, x + cell_width - 16, y + 218),
                                    radius=14, fill=(55, 42, 72, weapon_alpha))
            image = Image.alpha_composite(image, layer)
            draw = ImageDraw.Draw(image)
            draw.text((x + 24, y + 14), f'{index+1:02}', font=small, fill='#cda9df', **text_style)
            body = images.get(offer.identity)
            drawn = False
            if body:
                try:
                    with Image.open(BytesIO(body)) as source:
                        weapon = source.convert('RGBA')
                    weapon.thumbnail((cell_width - 54, 160), Image.Resampling.LANCZOS)
                    image.alpha_composite(weapon, (x + (cell_width - weapon.width) // 2,
                                                  y + 52 + (160 - weapon.height) // 2))
                    drawn = True
                except (OSError, ValueError):
                    pass
            draw = ImageDraw.Draw(image)
            if not drawn:
                text = '图片暂未加载'
                draw.text((x + (cell_width - small.getlength(text)) / 2, y + 112),
                          text, font=small, fill='#b9a7c8', **text_style)
            for line_index, line in enumerate(names[index]):
                draw.text((x + 28, y + 234 + line_index * 42), line,
                          font=name_font, fill='#fff8fc', **text_style)
            price = str(offer.price) + ' VP'
            draw.line((x + 28, y + row_height - 61, x + cell_width - 28,
                       y + row_height - 61), fill='#574466', width=1)
            draw.text((x + cell_width - 28 - price_font.getlength(price), y + row_height - 51),
                      price, font=price_font, fill='#f3d6ef', **text_style)
        y += row_height + gap
    fetched = datetime.fromtimestamp(shop.fetched_at, ZoneInfo('Asia/Shanghai'))
    draw = ImageDraw.Draw(image)
    draw.text((62, footer_y), fetched.strftime('更新于 %m月%d日 %H:%M（北京时间）'), font=small, fill='#dacbdf', **text_style)
    output = BytesIO()
    image.convert('RGB').save(output, 'PNG')
    return output.getvalue()
