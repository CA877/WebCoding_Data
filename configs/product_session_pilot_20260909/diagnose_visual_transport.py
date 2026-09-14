"""One bounded replay of the existing visual request for transport diagnosis."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--harness-root',type=Path,required=True)
parser.add_argument('--workdir',type=Path,required=True)
parser.add_argument('--round',type=int,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
signal.alarm(240)
sys.path.insert(0,str(args.harness_root))
from src.agents.vision_scorer import _perform_visual_review_request
from src.config import HarnessConfig
from src.orchestration.file_comm import FileComm
from src.orchestration.sprint_state import SprintState
credentials=json.loads(sys.stdin.readline())
config=HarnessConfig(evaluator_vision_model='gpt-5.5',evaluator_vision_endpoint_type='openai',
    evaluator_vision_api_key=credentials['TOKENWAVE_OPENAI_API_KEY'],
    evaluator_vision_base_url='https://api.tokenwave.us/v1',evaluator_vision_timeout_seconds=180,
    evaluator_vision_max_retries=0)
fc=FileComm(args.workdir/'.harness')
manifest=fc.read_visual_manifest(args.round)
started=time.monotonic()
review,stats=_perform_visual_review_request(config=config,file_comm=fc,workdir=args.workdir,
    sprint_num=1,sprint_context=SprintState.load(fc).sprint_context(1),
    screenshot_paths=manifest['screenshots'])
result={'status':'returned','elapsed_seconds':time.monotonic()-started,'model':'gpt-5.5',
    'reasoning_effort':'provider_default','screenshots':manifest['screenshots'],'review':review,'stats':asdict(stats)}
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
