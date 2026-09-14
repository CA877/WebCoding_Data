"""One bounded request through the same native TokenWave client used by this pilot."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'harness'))
from src.config import HarnessConfig
from src.agents.openai_runner import OpenAIHTTPClient


async def main():
    settings = json.load(sys.stdin)
    config = HarnessConfig(openai_api_key=settings['TOKENWAVE_OPENAI_API_KEY'],
        openai_base_url='https://api.tokenwave.us/v1')
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(OpenAIHTTPClient(config, timeout=90).complete(
            model='gpt-5.5', messages=[{'role':'user','content':'Reply with exactly API_OK.'}],
            max_completion_tokens=256, store=False), timeout=100)
        print(json.dumps({'status':'ok','elapsed':round(time.monotonic()-started,2),
            'message':result['choices'][0]['message']['content'],'usage':result.get('usage')}))
    except Exception as error:
        print(json.dumps({'status':'error','elapsed':round(time.monotonic()-started,2),
            'type':type(error).__name__, 'error':str(error)}))
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
