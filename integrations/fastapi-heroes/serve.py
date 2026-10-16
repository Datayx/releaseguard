"""Run the pinned third-party example locally, optionally injecting an update bug."""
import argparse
import os
from pathlib import Path
import sys
import types
import threading
import time

import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--broken', action='store_true', help='Discard age updates to demonstrate detection')
    parser.add_argument('--port', type=int, default=8002)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).parent / 'runtime')
    parser.add_argument('--shutdown-file', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    source_path = Path(__file__).with_name('upstream_api.py').resolve()
    source = source_path.read_text(encoding='utf-8')
    if args.broken:
        original = 'hero_data = hero.model_dump(exclude_unset=True)'
        if source.count(original) != 1:
            raise RuntimeError('Upstream source changed; cannot inject the expected fault')
        source = source.replace(original, original + '\n    hero_data.pop("age", None)  # Local fault injection')
    args.data_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(args.data_dir)
    # A dedicated module preserves type annotation resolution for FastAPI/SQLModel.
    module = types.ModuleType('heroes_target')
    module.__file__ = str(source_path)
    sys.modules[module.__name__] = module
    exec(compile(source, str(source_path), 'exec'), module.__dict__)
    print('Local update fault:', 'ON' if args.broken else 'OFF', flush=True)
    server = uvicorn.Server(uvicorn.Config(module.app, host='127.0.0.1', port=args.port, log_level='warning'))
    if args.shutdown_file:
        def watch_shutdown():
            while not server.should_exit:
                if args.shutdown_file.exists():
                    server.should_exit = True
                    return
                time.sleep(0.1)
        threading.Thread(target=watch_shutdown, daemon=True).start()
    try:
        server.run()
    finally:
        module.engine.dispose()


if __name__ == '__main__':
    main()
