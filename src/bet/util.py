def static_vars(**kwargs):
    def dec(func):
        for k in kwargs:
            setattr(func, k, kwargs[k])
        return func
    return dec
