"""Pure version/commit rules. Stability is exact normalized-text equality, not LocalAgreement."""
import unicodedata


def canonical(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC',text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


class Gate:
    def __init__(self, policy):
        if policy not in ('endpoint','eager','stable2'):raise ValueError('policy')
        self.policy=policy;self.revision=0;self.key='';self.text='';self.same=0
        self.final=False;self.active_draft=None;self.committed_draft=None
        self.buffer='';self.published='';self.rejected_pieces=0

    def observe(self, text, final=False):
        if self.final:raise ValueError('transcript already finalized')
        key=canonical(text)
        if final and not key:raise ValueError('empty final transcript')
        if key!=self.key:
            self.revision+=1;self.same=1;self.active_draft=None;self.buffer=''
        else:self.same+=1
        self.key,self.text,self.final=key,text,final
        if final and self.active_draft is not None:
            self.committed_draft=self.active_draft;self.published=self.buffer
        eligible=final or self.policy=='eager' or (self.policy=='stable2' and self.same>=2)
        return bool(key and self.active_draft is None and eligible)

    def attach(self, draft):
        if self.active_draft is not None or not self.key:raise ValueError('unsafe draft activation')
        self.active_draft=draft;self.buffer=''
        if self.final:self.committed_draft=draft

    def piece(self, draft, text):
        if draft!=self.active_draft:
            self.rejected_pieces+=1;return False
        self.buffer+=text
        if self.final:
            self.published+=text;return True
        return False


class LatestInput:
    """One pending ASR snapshot; the caller owns its already-running call."""
    def __init__(self):
        self.pending=None;self.replaced=0;self.last_offset=0;self.closed=False

    def offer(self, offset, final=False):
        if self.closed or type(offset) is not int or offset<=self.last_offset:
            raise ValueError('non-monotonic or post-final snapshot')
        self.last_offset=offset
        if self.pending is not None:self.replaced+=1
        self.pending=(offset,final)
        self.closed=final

    def take(self):
        item,self.pending=self.pending,None
        return item
