"""按句审核实验门；输入为已解码正文增量。协议解码放在独立适配器。
同步：完整窗口审完再发。异步：先发，审核结果回来后只停止后续发送。
"""
import asyncio
import time


async def moderate(source, review, emit, *, mode='sync', review_timeout=1,
                   max_chars=64, max_pending=8):
    if mode not in ('pass', 'sync', 'async') or min(max_chars, max_pending) < 1:
        raise ValueError('invalid gate configuration')
    queue = asyncio.Queue(maxsize=max_chars * max_pending)
    pending = {}
    checks = []
    emitted = 0
    consumed = 0
    buffered = ''
    offset = 0
    reader_task = None
    result = {'finish_reason': 'stop', 'blocked_start': None, 'blocked_end': None}

    async def produce():
        try:
            async for piece in source:
                if not isinstance(piece, str): raise TypeError('gate accepts decoded text')
                # 一条上游增量再大，也按有限字符块进入有界队列。
                for i in range(0, len(piece), max_chars):
                    await queue.put(piece[i:i+max_chars])
        except Exception as exc:
            await queue.put(exc)
        finally:
            await source.aclose()
        await queue.put(None)

    async def checked(text, start):
        begin = time.perf_counter()
        try:
            blocked = await asyncio.wait_for(review(text), review_timeout)
            if not isinstance(blocked, bool):
                reason = 'review_error'
            else:
                reason = 'content_filter' if blocked else 'allow'
        except asyncio.TimeoutError:
            reason = 'review_timeout'
        except Exception:
            reason = 'review_error'
        row = {'start': start, 'end': start+len(text), 'reason': reason,
               'ms': (time.perf_counter()-begin)*1000}
        checks.append(row)
        return row

    def apply(row):
        if row['reason'] == 'allow': return False
        result.update(finish_reason=row['reason'],blocked_start=row['start'],blocked_end=row['end'])
        return True

    async def completed(tasks):
        for task in sorted(tasks, key=lambda t: pending[t]):
            pending.pop(task)
            if apply(task.result()): return True
        return False

    async def submit(text, start):
        nonlocal emitted
        if mode == 'sync':
            if apply(await checked(text,start)): return True
            await emit(text); emitted += len(text)
        else:
            if len(pending) >= max_pending:
                # 允许已可运行的快速审核完成，避免一大块含多句时假性积压。
                ready, _ = await asyncio.wait(pending, timeout=.01, return_when=asyncio.FIRST_COMPLETED)
                if ready and await completed(ready):return True
            if len(pending) >= max_pending:
                result.update(finish_reason='review_backlog', blocked_start=start, blocked_end=start+len(text))
                return True
            task = asyncio.create_task(checked(text,start))
            pending[task] = start
        return False

    producer = asyncio.create_task(produce())
    try:
        while True:
            reader_task = asyncio.create_task(queue.get())
            while True:
                if producer.done():
                    if producer.cancelled():raise asyncio.CancelledError()
                    if producer.exception() is not None:raise producer.exception()
                watched={reader_task,*pending}
                if not producer.done():watched.add(producer)
                done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
                if producer in done:
                    if producer.cancelled():raise asyncio.CancelledError()
                    if producer.exception() is not None:raise producer.exception()
                review_done = done.intersection(pending)
                if review_done and await completed(review_done): return {**result, 'emitted_chars':emitted,'consumed_chars':consumed,'checks':checks}
                if reader_task in done: break
            piece = reader_task.result(); reader_task=None
            if isinstance(piece, Exception): raise piece
            if piece is None: break
            consumed += len(piece)
            if mode in ('pass','async'):
                await emit(piece); emitted += len(piece)
            if mode == 'pass':continue
            buffered += piece
            while buffered:
                cut = next((i+1 for i,ch in enumerate(buffered[:max_chars]) if ch in '。！？!?\n'), None)
                if cut is None and len(buffered)>=max_chars: cut=max_chars
                if cut is None:break
                text, buffered=buffered[:cut],buffered[cut:]
                if await submit(text,offset):
                    return {**result,'emitted_chars':emitted,'consumed_chars':consumed,'checks':checks}
                offset += len(text)
        if buffered and mode != 'pass':
            if await submit(buffered,offset):return {**result,'emitted_chars':emitted,'consumed_chars':consumed,'checks':checks}
        while pending:
            done,_=await asyncio.wait(pending,return_when=asyncio.FIRST_COMPLETED)
            if await completed(done):break
        return {**result,'emitted_chars':emitted,'consumed_chars':consumed,'checks':checks}
    finally:
        tasks=[producer,*pending]
        if reader_task is not None:tasks.append(reader_task)
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
