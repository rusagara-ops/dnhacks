export type TaskType = 'summarization' | 'document-qa' | 'information-extraction' | 'coding-assistance' | 'sentiment-classification';
export function createPayload(task_type: TaskType, source: string, instruction: string, sections = false): {task_type: TaskType; inputs: string[]; optimization: string; instruction?: string} {
  const bytes = (value: string) => new TextEncoder().encode(value).length;
  if (sections && task_type !== 'sentiment-classification') {
    const chunks = source.split(/\r?\n[ \t]*---[ \t]*\r?\n/);
    if (chunks.length > 1000) throw new Error('Use at most 1,000 sections.');
    if (chunks.reduce((sum, chunk) => sum + bytes(chunk), 0) > 1000000) throw new Error('Combined sections must fit within 1,000,000 UTF-8 bytes.');
    const validated = chunks.map(chunk => createPayload(task_type, chunk, instruction, false));
    return { ...validated[0], inputs: validated.flatMap(item => item.inputs) };
  }
  const inputs = task_type === 'sentiment-classification' ? parseInputs(source) : [source];
  if (!source.trim()) throw new Error('Enter a document or code snippet.');
  if (task_type !== 'sentiment-classification' && (bytes(source) > 6000 || [...source].length > 10000)) throw new Error('Source must be at most 6,000 UTF-8 bytes.');
  const request = ['document-qa', 'coding-assistance'].includes(task_type) ? instruction : '';
  if (task_type === 'document-qa' && !request.trim()) throw new Error('Enter a question about your document.');
  if (request && (!request.trim() || [...request].length > 1000)) throw new Error('The request must contain 1–1,000 nonblank characters.');
  if (request && bytes(source) + bytes(request) > 6500) throw new Error('Source plus request must fit within 6,500 UTF-8 bytes.');
  return { task_type, inputs, optimization: 'fastest', ...(request ? { instruction: request } : {}) };
}
export function parseInputs(text: string): string[] {
  const inputs = text.split(/\r?\n/).filter(line => line.trim().length > 0);
  if (!inputs.length) throw new Error('Enter at least one nonblank text input.');
  if (inputs.length > 1000) throw new Error('Use at most 1,000 inputs per job.');
  if (inputs.some(input => [...input].length > 10000)) throw new Error('Each input must contain at most 10,000 characters.');
  if (inputs.reduce((size, input) => size + new TextEncoder().encode(input).length, 0) > 1000000) throw new Error('Combined input text must not exceed 1,000,000 UTF-8 bytes.');
  return inputs;
}
