__all__ = ["StreamingCollector", "add_seeds_to_queue"]

# Resolved on first use (PEP 562). postprocessing imports GRAPH_ID_PREFIX from
# .storage to stay in step with what append_to_graph writes, and eager imports
# here would drag the crawler's aiohttp stack into the build parent and all 24
# of its workers for the sake of one constant.


def __getattr__(name: str):
    if name == "StreamingCollector":
        from .collector import StreamingCollector

        return StreamingCollector
    if name == "add_seeds_to_queue":
        from .seeds import add_seeds_to_queue

        return add_seeds_to_queue
    raise AttributeError(name)
