"""跨异步/线程边界时，重复取消也必须等真实推理调用收拢。"""
import asyncio

async def joined_thread_call(function,*args):
    task=asyncio.create_task(asyncio.to_thread(function,*args))
    cancelled=False
    while True:
        try:
            value=await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            cancelled=True
            if task.done():break
        except BaseException:
            if cancelled:raise asyncio.CancelledError() from None
            raise
    if cancelled:raise asyncio.CancelledError()
    return value
