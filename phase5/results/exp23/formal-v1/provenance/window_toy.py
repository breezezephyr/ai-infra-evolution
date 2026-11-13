"""Finite-window layered integer sums, a teaching counterexample, not attention."""


def forward(tokens, window, layers, start=0):
    previous=[v if i>=start else 0 for i,v in enumerate(tokens)]
    for _ in range(layers):
        current=[0]*len(tokens)
        for i in range(start,len(tokens)):
            current[i]=sum(previous[max(start,i-window+1):i+1])
        previous=current
    return previous


def compare(tokens, window, backtrack, layers, keep):
    if not tokens or window<1 or layers<1 or keep<1 or backtrack<0 or backtrack>=len(tokens):
        raise ValueError('invalid toy geometry')
    start=max(0,len(tokens)-keep);query=len(tokens)-1-backtrack
    row={'window':window,'backtrack':backtrack,'layers':layers,'keep':keep,
         'start':start,'query':query,'single_window_covered':start<=max(0,query-window+1),
         'dependency_covered':start<=max(0,query-layers*(window-1))}
    if query<start:
        return {**row,'status':'query_evicted','full':forward(tokens,window,layers)[query],
                'mask':None,'compact':None,'full_equal':False}
    full=forward(tokens,window,layers)[query]
    mask=forward(tokens,window,layers,start)[query]
    compact=forward(tokens[start:],window,layers)[query-start]
    return {**row,'status':'compared','full':full,'mask':mask,'compact':compact,'full_equal':full==mask==compact}
