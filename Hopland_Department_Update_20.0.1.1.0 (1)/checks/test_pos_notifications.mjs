import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
let notifications = [], timers = [], calls = [], cursorResults = [], dialogs=[];
class PosStore {
    async setup() {
        this.config={id:9, hopland_birthday_enabled:true};
        this.data={network:{offline:false},call:async(model,method,args)=>{
            calls.push(args);
            const r=cursorResults.shift(); if(r instanceof Error) throw r; return r;
        }};
        this.notification={add:(...args)=>notifications.push(args)};
        this.dialog={add:(...args)=>dialogs.push(args)};
    }
}
function patch(target, extension) {
    const parent = Object.create(Object.getPrototypeOf(target), Object.getOwnPropertyDescriptors(target));
    Object.setPrototypeOf(extension,parent);
    Object.defineProperties(target,Object.getOwnPropertyDescriptors(extension));
}
const context=vm.createContext({patch,PosStore,BirthdayDialog:class{},setTimeout:(cb,ms)=>{timers.push({cb,ms});return timers.length;}});
vm.runInContext(fs.readFileSync(new URL('../hopland_birthday_pos/static/src/department_notifications.js',import.meta.url),'utf8').replace(/^import .*;\n/gm,''),context);
cursorResults.push({cursor:4,bookings:[{id:4,reference:'BDAY/4'}]});
const store=new PosStore();await store.setup();await new Promise(r=>setImmediate(r));
assert.equal(calls[0][0],9);assert.equal(calls[0][1],null);assert.equal(store.hoplandSalesCursor,4);
assert.equal(notifications.length,1);assert.equal(timers[0].ms,15000);
notifications[0][1].buttons[0].onClick();assert.equal(dialogs[0][1].initialTab,'bookings');
cursorResults.push(new Error('offline'));await timers.shift().cb();
assert.equal(store.hoplandSalesCursor,4);
cursorResults.push({cursor:5,bookings:[{id:5,reference:'BDAY/5'}]});await timers.shift().cb();
assert.equal(store.hoplandSalesCursor,5);assert.equal(notifications.length,2);
cursorResults.push({cursor:5,bookings:[]});await timers.shift().cb();assert.equal(notifications.length,2);
store.data.network.offline=true;const count=calls.length;await timers.shift().cb();assert.equal(calls.length,count);
console.log('PASS: initial arrivals, correct register, notification action, retry cursor, new arrivals, no duplicates, offline pause, 15-second interval');
