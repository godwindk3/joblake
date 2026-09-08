const check = (({number, previous, selector}) => {
                const root = document.querySelector('ul.pagination');
                const active = root?.querySelector('li.active button')?.textContent.trim();
                const buttons = root ? [...root.querySelectorAll('button')] : [];
                const target = buttons.find(b => b.textContent.trim() === String(number));
                const next = buttons.find(b => b.textContent.trim() === '>');
                const disabled = b => b.disabled || b.getAttribute('aria-disabled') === 'true';
                let state = null;
                if (active === String(number)) state = 'arrived';
                else if (active === String(previous) && document.querySelector(selector)
                         && !document.querySelector('[aria-busy="true"]')) {
                    if (target && !disabled(target)) state = 'number';
                    else if (next && !disabled(next)) state = 'next';
                    else if (!target && next && disabled(next)) state = 'end';
                }
                const key = `${number}:${active}:${state}`;
                const now = performance.now();
                if (window.__joblakePagination?.key !== key)
                    window.__joblakePagination = {key, since: now};
                return state && now - window.__joblakePagination.since >= 1500 ? state : false;
            });

const assert = require('node:assert/strict');
let now = 0, active = '11', buttons = [], busy = false, jobs = true;
global.window = {};
global.performance = {now: () => now};
const root = {querySelector: () => ({textContent: active}), querySelectorAll: () => buttons};
global.document = {querySelector: s => s === 'ul.pagination' ? root : s === '[aria-busy="true"]' ? busy : jobs};
const args = {number:12, previous:11, selector:'h2 a'};
const button = (text, disabled=false) => ({textContent:text, disabled, getAttribute:()=>null});
const stable = () => { check(args); now += 1600; return check(args); };
assert.equal(stable(), false); // missing pagination never means end
buttons = [button('12')];
assert.equal(check(args), false); // rendering must settle
assert.equal(stable(), 'number'); // control appears after temporary absence
buttons = [button('>')];
assert.equal(stable(), 'next');
buttons = [button('>', true)]; busy = true;
assert.equal(stable(), false); // loading cannot establish end
busy = false; jobs = false;
assert.equal(stable(), false);
jobs = true;
assert.equal(stable(), 'end'); // explicit, stable disabled next
active = '12';
assert.equal(stable(), 'arrived');
active = '1';
assert.equal(stable(), false); // wrong page never accepted
console.log('9 pagination DOM-state checks passed');
