/* Optional mathematical regression tests. Requires Node.js; the explorer does not.
   node test_web_trip_explorer.cjs [path/to/jsons] [path/to/old/web_audit.json]
*/
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const html=fs.readFileSync(path.join(__dirname,'web_trip_explorer.html'),'utf8');
const core=html.match(/<script id="web-math">([\s\S]*?)<\/script>/)[1];
const exportsObject={exports:{}};Function('module',core)(exportsObject);const M=exportsObject.exports;
let files=0,values=0,conflicts=0;
function balance(w){let counts=[0,0,0,0];const prefixes=[];for(const x of w){counts[+x-1]++;prefixes.push([...counts]);}const js=[];let lower=2;for(let i=0;i<3;i++){let j=lower;while(prefixes[j-1][i]!==prefixes[j-1][i+1])j++;js.push(j);lower=j;}const letters=[...w].map(Number);for(const j of [1,...js])letters[j-1]=M.mod(letters[j-1]-2,4)+1;return {crossing:js,word:[...letters.slice(1),letters[0]].join('')};}
function checkPromotion(word){const p=M.promotion(word);let w=word;
  for(let b=1;b<=16;b++){const q=balance(w),stage=p.stages[b-1];assert.deepEqual(stage.crossing,q.crossing);assert.equal(M.wordOf(stage.after),q.word);assert.equal(stage.frames.length,7);assert(stage.frames.every(t=>t.flat().filter(x=>x===null).length===1));w=q.word;}
  assert.equal(w,word);for(const q of p.permutations)assert.deepEqual([...q].sort((a,b)=>a-b),Array.from({length:16},(_,i)=>i+1));
  for(let b=1;b<=16;b++){assert.equal(p.permutations[2][p.permutations[0][b-1]-1],b);assert.equal(p.permutations[1][p.permutations[1][b-1]-1],b);}
  const next=M.promotion(M.wordOf(p.stages[0].after));for(let i=0;i<3;i++)for(let b=1;b<=16;b++)assert.equal(next.permutations[i][b-1],M.mod(p.permutations[i][b%16]-2,16)+1);
  return p;
}
const fig=checkPromotion('1123212133444234');assert.deepEqual(fig.permutations,[[5,3,4,14,13,7,10,9,12,11,6,2,1,15,16,8],[10,4,13,2,15,9,12,11,6,1,8,7,3,16,5,14],[13,12,2,3,1,11,6,16,8,7,10,9,5,4,14,15]]);
const embedded=JSON.parse(html.match(/<script id="example-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
assert(M.compare(M.trips(M.graph(embedded)).permutations,checkPromotion(embedded.word).permutations).pass);
const wrong=M.promotion('1111222233334444');assert(!M.compare(M.trips(M.graph(embedded)).permutations,wrong.permutations).pass);
assert.throws(()=>M.tableau('2111222233334444'));assert.throws(()=>M.tableau('1234'));assert.throws(()=>M.graph({nodes:[],edges:[]}));
assert.deepEqual(M.inferWord({},'unknown.json'),{word:'',source:'Enter a tableau word'});
assert.equal(M.inferWord({},'orbit_1_exposed.json').word,'1111222233334444');assert.equal(M.inferWord({},'orbit_1_spliced.json').word,'1121323142324344');assert.equal(M.inferWord({},'orbit_1_unzipped.json').word,'1212341234123434');
const ref=process.argv[3]?JSON.parse(fs.readFileSync(process.argv[3],'utf8')):null;
if(process.argv[2])for(const name of fs.readdirSync(process.argv[2]).filter(n=>/\.json$/i.test(n))){const data=JSON.parse(fs.readFileSync(path.join(process.argv[2],name),'utf8'));const g=M.graph(data),t=M.trips(g),w=M.inferWord(data,name),p=checkPromotion(w.word),result=M.compare(t.permutations,p.permutations);assert(result.pass,`${name} has trip/promotion mismatches`);if(ref){const r=ref.files.find(r=>r.file===name);assert(r,`${name} missing in reference audit`);assert.deepEqual(t.permutations,r.trip_permutations);assert.deepEqual(p.permutations,r.promotion_permutations);}files++;values+=48;conflicts+=g.orderConflicts;}
console.log(JSON.stringify({status:'PASS',figure_1_benchmark:true,independent_balance_point_algorithm:true,promotion_rotation_and_inverse_properties:true,invalid_inputs_rejected:true,wrong_tableau_detected:true,files,trip_values:values,source_hourglass_order_conflicts:conflicts,python_reference_compared:!!ref},null,2));
