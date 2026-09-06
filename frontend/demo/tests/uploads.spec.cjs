const {test,expect}=require('@playwright/test');
const fs=require('node:fs/promises');
const path=require('node:path');
function pdf(text) {
 const stream=text ? `BT /F1 12 Tf 40 100 Td (${text}) Tj ET` : '';
 const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>','<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`];
 let body='%PDF-1.4\n', offsets=[0];
 objects.forEach((object,i)=>{offsets.push(Buffer.byteLength(body));body+=`${i+1} 0 obj\n${object}\nendobj\n`;});
 const start=Buffer.byteLength(body);body+='xref\n0 6\n0000000000 65535 f \n'+offsets.slice(1).map(n=>String(n).padStart(10,'0')+' 00000 n \n').join('');
 return Buffer.from(body+`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`);
}
async function setup(page) {
 const submissions=[];let count=0;
 await page.route('https://tile.openstreetmap.org/**',r=>r.abort());
 await page.route('http://127.0.0.1:8000/**',async route=>{
 const u=new URL(route.request().url());
 if(u.pathname.startsWith('/demo/')){
  const name=u.pathname==='/demo/'?'index.html':u.pathname.slice(6);
  return route.fulfill({body:await fs.readFile(path.join(__dirname,'..',name)),contentType:/\.m?js$/.test(name)?'text/javascript':name.endsWith('.css')?'text/css':name.endsWith('.html')?'text/html':'application/octet-stream'});
 }
 if(u.pathname==='/api/jobs' && route.request().method()==='POST') {const body=route.request().postDataJSON();submissions.push(body);count=body.inputs.length;return route.fulfill({status:201,json:{job_id:'job1'}});}
 if(u.pathname.endsWith('/results'))return route.fulfill({json:{job_id:'job1',status:'COMPLETED',is_final:true,total_inputs:count,completed_inputs:count,failed_inputs:0,failed_tasks:[],tasks:Array.from({length:count},(_,i)=>({task_id:'t'+i,input_start_index:i,input_count:1,status:'COMPLETED',worker_id:'w'+i,worker_name:'Computer '+i,attempt_count:1,execution_time_ms:100})),results:Array.from({length:count},(_,i)=>({index:count-i-1,text:'Summary '+(count-i)}))}});
 if(u.pathname==='/api/jobs')return route.fulfill({json:count?[{id:'job1',task_type:'summarization',status:'COMPLETED',total_tasks:count,model_id:'test',created_at:new Date().toISOString()}]:[]});
 if(u.pathname==='/api/jobs/job1')return route.fulfill({json:{id:'job1',task_type:'summarization',status:'COMPLETED',total_tasks:count}});
 if(u.pathname==='/api/workers')return route.fulfill({json:[{id:'w0',device_id:'w0',name:'Computer 0',hostname:'test',status:'AVAILABLE',models:[{model_id:'test-model',model_revision:'test',supported_tasks:['summarization']}],supported_tasks:['summarization']}]});
 if(u.pathname==='/api/activity')return route.fulfill({json:{active_tasks:[],recent_tasks:count?[{task_id:'t0',job_id:'job1',task_type:'summarization',status:'COMPLETED',worker_name:'Computer 0',start_index:0,input_count:1,attempt_count:1}]:[],worker_metrics:[],retries:0,task_counts:{}}});
 if(u.pathname.includes('/locations'))return route.fulfill({json:{items:[],total:0,limit:50,offset:0,distance_reference:'coordinator'}});
 return route.fulfill({json:[]});
 });
 await page.goto('http://127.0.0.1:8000/demo/');await page.locator('#connect').click();await expect(page.locator('#connection')).toContainText('Connected');
 await page.getByRole('button',{name:'Use this worker',exact:true}).click();await page.locator('#model').selectOption('test-model');
 await page.getByLabel('Upload documents',{exact:true}).check();return submissions;
}
test('TXT batch maps out-of-order results to filenames and retains names after reload',async({page})=>{
 const submissions=await setup(page);
 await page.locator('#document-files').setInputFiles([{name:'first.txt',mimeType:'text/plain',buffer:Buffer.from('One\n\nWhole document')},{name:'second.txt',mimeType:'text/plain',buffer:Buffer.from('Second document')}]);
 await expect(page.locator('#upload-status')).toContainText('2 ready');await page.locator('#submit').click();
 await expect(page.locator('#results')).toContainText('first.txt');
 expect(submissions[0].inputs).toEqual(['One\n\nWhole document','Second document']);
 await expect(page.locator('#results article').first()).toContainText('Summary 1');
 await page.reload();await page.locator('#connect').click();await page.locator('#activity .activity-row').first().click();await page.locator('#activity-detail button').click();await expect(page.locator('#results')).toContainText('second.txt');
});
test('PDF extraction works and scanned/oversized files block submission until removed',async({page})=>{
 await setup(page);
 await page.locator('#document-files').setInputFiles([{name:'source.pdf',mimeType:'application/pdf',buffer:pdf('Hello from a PDF document')}]);
 await expect(page.locator('#upload-status')).toContainText('1 ready',{timeout:30000});
 await page.locator('#document-list summary').click();await expect(page.locator('#document-list pre')).toContainText('Hello from a PDF document');
 await page.locator('#document-files').setInputFiles([{name:'scan.pdf',mimeType:'application/pdf',buffer:pdf('')},{name:'long.txt',mimeType:'text/plain',buffer:Buffer.from('a'.repeat(6001))}]);
 await expect(page.locator('#document-list')).toContainText('no extractable text',{timeout:30000});
 await expect(page.locator('#document-list')).toContainText('6,000');await expect(page.locator('#submit')).toBeDisabled();
 await page.locator('.upload-document').filter({hasText:'scan.pdf'}).getByText('Remove',{exact:true}).click();
 await page.locator('.upload-document').filter({hasText:'long.txt'}).getByText('Remove',{exact:true}).click();await expect(page.locator('#submit')).toBeEnabled();
});
test('uncertain submission blocks duplicate POSTs until explicit acknowledgment',async({page})=>{
 await setup(page);let attempts=0;
 await page.locator('#document-files').setInputFiles({name:'one.txt',mimeType:'text/plain',buffer:Buffer.from('One document')});
 await expect(page.locator('#upload-status')).toContainText('1 ready');
 await page.route('**/api/jobs',route=>{if(route.request().method()==='POST'){attempts++;return route.abort();}return route.fallback();});
 await page.locator('#submit').click();await expect(page.locator('#retry-submission')).toBeVisible();await expect(page.locator('#submit')).toBeDisabled();expect(attempts).toBe(1);
 await page.locator('#retry-submission').click();await expect(page.locator('#submit')).toBeEnabled();
});
