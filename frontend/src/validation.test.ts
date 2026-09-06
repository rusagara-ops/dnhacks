import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseInputs } from './validation.ts';

test('preserves input whitespace and Unicode while ignoring empty lines', () => {
  assert.deepEqual(parseInputs('  hello  \r\n\n  \n😀'), ['  hello  ', '😀']);
  assert.equal(parseInputs('😀'.repeat(10000))[0].length, 20000);
});
test('enforces all backend payload limits', () => {
  for (const text of ['', ' \n ', Array(1001).fill('a').join('\n'), 'a'.repeat(10001), Array(26).fill('😀'.repeat(10000)).join('\n')]) assert.throws(() => parseInputs(text));
  assert.equal(parseInputs(Array(100).fill('a'.repeat(10000)).join('\n')).length, 100);
});

import { createPayload } from './validation.ts';
test('document modes preserve paragraphs and code; mode changes omit irrelevant instructions', () => {
  const source = 'first paragraph\n\n  second paragraph';
  assert.deepEqual(createPayload('summarization', source, 'old question'), {task_type:'summarization', inputs:[source], optimization:'fastest'});
  assert.deepEqual(createPayload('coding-assistance', source, 'Explain'), {task_type:'coding-assistance', inputs:[source], optimization:'fastest', instruction:'Explain'});
  assert.equal(createPayload('document-qa', source, 'Why?').instruction, 'Why?');
  assert.deepEqual(createPayload('sentiment-classification', 'good\nbad', '').inputs, ['good','bad']);
});
test('new task contracts reject missing questions and oversized UTF-8 payloads', () => {
  assert.throws(() => createPayload('document-qa', 'source', ''));
  assert.throws(() => createPayload('coding-assistance', 'source', ' '));
  assert.throws(() => createPayload('summarization', '😀'.repeat(1501), ''));
  assert.throws(() => createPayload('coding-assistance', 'a'.repeat(6000), 'b'.repeat(501)));
  assert.throws(() => createPayload('document-qa', 'a', 'b'.repeat(1001)));
  assert.equal(createPayload('information-extraction', '😀'.repeat(1500), '').inputs.length, 1);
  assert.equal(createPayload('document-qa', 'a'.repeat(6000), 'b'.repeat(500)).instruction?.length, 500);
});

test('section mode creates independently validated inputs without losing paragraphs', () => {
  const source = 'Part one\n\nMore context\n---\nPart two';
  assert.deepEqual(createPayload('summarization',source,'',true).inputs,['Part one\n\nMore context','Part two']);
  assert.equal(createPayload('summarization',Array(10).fill('section').join('\n---\n'),'',true).inputs.length,10);
  assert.throws(() => createPayload('summarization','first\n---\n','',true));
  assert.throws(() => createPayload('summarization','a\n---\n'+'b'.repeat(6001),'',true));
  assert.deepEqual(createPayload('summarization',source,'',false).inputs,[source]);
});
