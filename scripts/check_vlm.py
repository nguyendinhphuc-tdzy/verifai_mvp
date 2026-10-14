"""Live Ollama connectivity + schema smoke test on synthetic content. No quality claims."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verifai_core.vlm import OllamaVLM, VLMError


def main():
    try:
        client=OllamaVLM()
        status=client.check()
        print('Ollama status:',status)
        if not status['ready']:
            print('Start Ollama and run: ollama pull',client.model)
            return 1
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
    except (VLMError, OSError, ValueError) as exc:
        print('LIVE MODEL SMOKE TEST FAILED:',exc)
        return 1

if __name__=='__main__':raise SystemExit(main())
