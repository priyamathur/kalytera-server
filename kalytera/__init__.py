from kalytera.tracer import check, init, trace, watch

# Standard SDK convention alias — kalytera.configure() == kalytera.init()
configure = init

__all__ = ["init", "configure", "trace", "watch", "check"]
