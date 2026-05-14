# resources.lib.modules package
# Expose a top-level `cfscrape` alias when our copy is available so external
# scrapers that do `import cfscrape` will resolve to our implementation.
try:
    import importlib
    import sys
    _mod = importlib.import_module('.cfscrape', __package__)
    sys.modules.setdefault('cfscrape', _mod)
except Exception:
    # Silently ignore; this is just a convenience alias for import resolution
    pass
