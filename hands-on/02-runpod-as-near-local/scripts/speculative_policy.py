"""Causal retention policy; no future arrivals are accepted by this interface."""
class Policy:
    def __init__(self, name):
        assert name in ('keep', 'delete', 'fixed20', 'predict')
        self.name=name
        self.ewma=10.
        self.previous=None

    def arrival(self, timestamp):
        if self.previous is not None:
            assert timestamp >= self.previous
            self.ewma=.5*(timestamp-self.previous)+.5*self.ewma
        self.previous=timestamp

    def ttl(self):
        return {'keep':float('inf'),'delete':0.,'fixed20':20.,
                'predict':min(60.,max(5.,4*self.ewma))}[self.name]

ARRIVALS=[0.,8.,16.,46.,54.,62.,132.,140.,148.]
HORIZON=175.
