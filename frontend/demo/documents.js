/* Browser-local extraction. Only validated text is submitted to the coordinator. */
window.Documents = (() => {
  const bytes = text => new TextEncoder().encode(text).length;
  const MAX_FILES = 100, MAX_FILE_BYTES = 10 * 1024 * 1024;
  function validate(entries, instruction = '') {
    if (!entries.length) throw Error('Choose at least one document.');
    if (entries.length > MAX_FILES) throw Error('Choose at most 100 documents per batch.');
    if ([...instruction].length > 1000) throw Error('Your question or request must be at most 1,000 characters.');
    let total = 0;
    for (const entry of entries) {
      if (entry.error || typeof entry.text !== 'string') throw Error(`${entry.name}: ${entry.error || 'Still parsing.'}`);
      if (!entry.text.trim()) throw Error(`${entry.name}: no readable text found.`);
      const size = bytes(entry.text); total += size;
      if (size > 6000) throw Error(`${entry.name}: ${size.toLocaleString()} UTF-8 bytes; the current limit is 6,000. Nothing was truncated.`);
      if (size + bytes(instruction) > 6500) throw Error(`${entry.name}: document plus request exceeds 6,500 UTF-8 bytes.`);
    }
    if (total > 1000000) throw Error('Combined document text exceeds 1,000,000 UTF-8 bytes.');
    return entries.map(entry => entry.text);
  }
  let library;
  async function pdfText(file) {
    library ??= import('/demo/vendor/pdfjs/pdf.mjs');
    const pdfjs = await library;
    pdfjs.GlobalWorkerOptions.workerSrc = '/demo/vendor/pdfjs/pdf.worker.mjs';
    const task = pdfjs.getDocument({data: new Uint8Array(await file.arrayBuffer()),
      cMapUrl: '/demo/vendor/pdfjs/cmaps/', cMapPacked: true,
      standardFontDataUrl: '/demo/vendor/pdfjs/standard_fonts/',
      isEvalSupported: false, enableXfa: false, stopAtErrors: true});
    let timer;
    const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(Error('PDF parsing timed out. Try a smaller document.')), 20000); });
    try {
      return await Promise.race([timeout, (async () => {
        const pdf = await task.promise;
        if (pdf.numPages > 100) throw Error('PDFs may contain at most 100 pages.');
        const pages = [];
        for (let index = 1; index <= pdf.numPages; index++) {
          const page = await pdf.getPage(index);
          const content = await page.getTextContent();
          const text = content.items.filter(item => typeof item.str === 'string')
            .map(item => item.str + (item.hasEOL ? '\n' : ' ')).join('').trim();
          if (!text) throw Error(`Page ${index} has no extractable text. Scanned/image-only or blank pages are unsupported; OCR is not included.`);
          pages.push(text); page.cleanup();
          if (bytes(pages.join('\n\n')) > 6000) throw Error('Extracted PDF text exceeds 6,000 UTF-8 bytes. Nothing was truncated.');
        }
        return pages.join('\n\n');
      })()]);
    } catch (error) {
      if (error.name === 'PasswordException') throw Error('Password-protected PDFs are not supported. Upload an unlocked copy.');
      throw error;
    } finally { clearTimeout(timer); await task.destroy(); }
  }
  async function parse(file) {
    if (file.size > MAX_FILE_BYTES) throw Error('File exceeds the 10 MiB upload limit.');
    if (!file.size) throw Error('File is empty.');
    let text;
    if (/\.txt$/i.test(file.name)) text = new TextDecoder('utf-8', {fatal:true}).decode(await file.arrayBuffer());
    else if (/\.pdf$/i.test(file.name)) text = await pdfText(file);
    else throw Error('Supported formats: UTF-8 TXT and text-based PDF.');
    if (text.includes('\0')) throw Error('File contains binary data, not plain text.');
    validate([{name:file.name,text}]);
    return text;
  }
  return {parse, validate, bytes, MAX_FILES};
})();
