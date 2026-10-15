"""One place for group mentions; upstream text is never parsed as CQ code."""
from nonebot.adapters.onebot.v11 import Message, MessageSegment


def addressed_message(qq, content, *, group=True):
    message = Message()
    if group:
        message += MessageSegment.at(qq)
        message += MessageSegment.text('\n')
    if isinstance(content, bytes):
        message += MessageSegment.image(content)
    elif isinstance(content, str):
        message += MessageSegment.text(content)
    else:
        message += content
    return message
