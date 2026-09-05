"""Pinned, CPU-compatible English summary inference for the three-Mac demo."""
import os
from pathlib import Path

MODEL_ID = 'Qwen/Qwen2.5-0.5B-Instruct'
MODEL_REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'


class Summarizer:
    def __init__(self):
        os.environ.setdefault('HF_HOME', str(Path(__file__).resolve().parent / '.cache/huggingface'))
        os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, revision=MODEL_REVISION, use_safetensors=True).eval()

    def predict(self, task):
        if (task['model_id'], task['model_revision'], task['task_type']) != (
                MODEL_ID, MODEL_REVISION, 'summarization'):
            raise ValueError('Unsupported inference contract')
        results = []
        for item in task['inputs']:
            source = self.tokenizer.decode(self.tokenizer.encode(item['text'], add_special_tokens=False)[:512], skip_special_tokens=True)
            prompt = self.tokenizer.apply_chat_template([
                {'role': 'system', 'content': 'Summarize the provided text in one short sentence. Use only facts stated in the text. Return only the summary.'},
                {'role': 'user', 'content': source}], tokenize=False, add_generation_prompt=True)
            tokens = self.tokenizer(prompt, return_tensors='pt')
            with self.torch.inference_mode():
                output = self.model.generate(**tokens, max_new_tokens=64, do_sample=False)
            summary = self.tokenizer.decode(output[0, tokens.input_ids.shape[1]:], skip_special_tokens=True).strip()
            if not summary:
                raise ValueError('Empty model output')
            results.append({'index': item['index'], 'text': summary})
        return results
