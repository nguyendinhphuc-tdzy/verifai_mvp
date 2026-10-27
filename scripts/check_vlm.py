"""Live Gemini connectivity + schema smoke test on synthetic content. No quality claims."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import argparse
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verifai_core.vlm import VLMError
from verifai_core.gemini import GeminiVLM


def main():
    parser=argparse.ArgumentParser(description='Check Gemini API connectivity and vision schema')
    parser.add_argument('--text-only',action='store_true',
                        help='Send a tiny text prompt to diagnose server reachability')
    args=parser.parse_args()
    try:
        client=GeminiVLM()
        status=client.check()
        print('Gemini status:',status)
        if not status['ready']:
            print('Set GEMINI_API_KEY and install google-genai')
            return 1
        if args.text_only:
            from google.genai import types
            response=client._get_client().models.generate_content(
                model=client.model,
                contents='Reply with exactly: OK',
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_level='low')))
            if not (response.text or '').strip():
                raise VLMError('Gemini returned an empty text response')
            print('TEXT-ONLY GEMINI CHECK PASSED. Response:',response.text.strip()[:100])
            return 0
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.jpg'
            image=np.full((280,460,3),(238,238,238),dtype=np.uint8)
            cv2.rectangle(image,(120,65),(320,245),(180,205,225),-1)
            cv2.putText(image,'DEMO', (155,145),cv2.FONT_HERSHEY_SIMPLEX,1.2,(25,25,25),3)
            cv2.imwrite(str(path),image)
            product={'sku':'DEMO-01','name':'Synthetic demonstration box','brand':'DEMO',
                     'claims':[],'banned':[]}
            result=client.analyze([path],product,'single')
            print(result.model_dump_json(indent=2))
            print('LIVE MODEL SMOKE TEST PASSED. This is not an accuracy benchmark.')
        return 0
    except Exception as exc:
        print('LIVE MODEL SMOKE TEST FAILED:',exc)
        return 1

if __name__=='__main__':raise SystemExit(main())
