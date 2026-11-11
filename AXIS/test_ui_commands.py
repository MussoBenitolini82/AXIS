"""Execute UI command handlers with mocked DOM/network; no external requests."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for JavaScript behavior tests')
class UICommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path(__file__).with_name('index.html').read_text(encoding='utf-8')

    def run_js(self, source):
        result = subprocess.run(['node', '-'], input=source, text=True,
                                encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def research_source(self):
        norm = self.html.split('function norm(s)', 1)[1].split('\n', 1)[0]
        detail = self.html.split('function researchDetail(detail)', 1)[1].split('\n', 1)[0]
        command = self.html.split('async function cmdResearch(topic,limit)', 1)[1].split('\nfunction help()', 1)[0]
        return ("const assert=require('node:assert/strict');\n"
                "const RESEARCH_DEFAULT=50,pendingResearch=new Set(),myJobs=new Set();let researchJobs=[];"
                "const answers=[];function localAnswer(...args){answers.push(args)}"
                "function feed(){} async function reload(){}\n"
                'function norm(s)' + norm + '\nfunction researchDetail(detail)' + detail +
                '\nasync function cmdResearch(topic,limit)' + command + '\n')

    def test_inline_scripts_parse(self):
        scripts = re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', self.html, re.S)
        import json
        self.run_js("const vm=require('node:vm');" +
                    ''.join('new vm.Script(' + json.dumps(s) + ');' for s in scripts))

    def test_research_prevents_pending_and_running_duplicates(self):
        self.run_js(self.research_source() + """
        (async()=>{
          let calls=0,release;
          global.fetch=async()=>{calls++;return new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({job_id:'j1'})})})};
          const first=cmdResearch('Sinir Ağı',50);
          await cmdResearch('sinir   ağı',50);
          assert.equal(calls,1);assert.match(answers[0][1],/zaten sürüyor/);
          release();await first;
          assert.deepEqual([...myJobs],['j1']);
          assert.match(answers[1][1],/arXiv/);
          await cmdResearch('SİNİR AĞI',100);
          assert.equal(calls,1);assert.equal(pendingResearch.size,0);
          researchJobs=[];
          const next=cmdResearch('Başka konu',50);assert.equal(calls,2);release();await next;
        })().catch(e=>{console.error(e);process.exitCode=1});
        """)

    def test_research_429_is_explained_and_pending_guard_released(self):
        self.run_js(self.research_source() + """
        (async()=>{
          global.fetch=async()=>({ok:false,status:429,json:async()=>({error:'Too Many Requests'})});
          await assert.rejects(cmdResearch('sinir ağı',50), /OpenAlex.*HTTP 429/);
          assert.equal(pendingResearch.size,0);assert.equal(researchJobs.length,0);assert.equal(myJobs.size,0);
          assert.match(researchDetail('HTTP Error 429: Too Many Requests'), /Bir süre bekleyip/);
          assert.equal(researchDetail('3 akademik kayıt işlendi'),'3 akademik kayıt işlendi');
          assert.equal(researchDetail('429 akademik kayıt işlendi'),'429 akademik kayıt işlendi');
          global.fetch=async()=>{throw Error('offline')};
          await assert.rejects(cmdResearch('sinir ağı',50),/offline/);
          assert.equal(pendingResearch.size,0);
        })().catch(e=>{console.error(e);process.exitCode=1});
        """)

    def test_tracked_research_notices_preserve_fallback_details_once(self):
        render = self.html.split('function renderJobs(jobs){', 1)[1].split('\nasync function reload()', 1)[0]
        self.run_js(self.research_source() + """
        let jobSeen=new Map();
        const root={replaceChildren(){},append(){}};
        const $=()=>root;
        function el(){return {dataset:{}}}function toast(){}function setSt(){}
        function renderJobs(jobs){
        """ + render + """
        myJobs.add('done');myJobs.add('failed');
        const jobs=[{id:'done',topic:'konu',status:'completed',details:'OpenAlex HTTP 429; arXiv: 10 kayıt'},
                    {id:'failed',topic:'diğer',status:'failed',details:'HTTP Error 429: Too Many Requests'}];
        renderJobs(jobs);
        assert.equal(myJobs.size,0);assert.equal(answers.length,2);
        assert.match(answers[0][1],/arXiv: 10 kayıt/);
        assert.equal(answers[1][3],'failed');assert.match(answers[1][1],/Bir süre bekleyip/);
        renderJobs(jobs);assert.equal(answers.length,2);
        """)

    def test_enter_reentry_blocked_and_new_draft_preserved(self):
        handler = self.html.split("$('#cmd').addEventListener('submit',async e=>{", 1)[1].split('\n});', 1)[0]
        self.run_js("""
        const assert=require('node:assert/strict');
        const cmdInput={value:'first'},go={disabled:false};let runs=0,release;
        const $=()=>go;function parseIntent(){return {name:'test',path:'local',run:()=>{runs++;return new Promise(r=>release=r)}}}
        function showIntent(){}function feed(){}function autogrow(){}function localAnswer(){}
        const submit=async e=>{
        """ + handler + """
        };
        (async()=>{
          const event={preventDefault(){}};
          const first=submit(event);assert.equal(go.disabled,true);
          await submit(event);assert.equal(runs,1);
          cmdInput.value='new draft';release();await first;
          assert.equal(cmdInput.value,'new draft');assert.equal(go.disabled,false);
          const next=submit(event);release();await next;
          assert.equal(cmdInput.value,'');assert.equal(runs,2);
        })().catch(e=>{console.error(e);process.exitCode=1});
        """)


if __name__ == '__main__':
    unittest.main()
