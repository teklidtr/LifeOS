import assert from "node:assert/strict";
import test from "node:test";
import { BridgeClient, HandshakeResult, LifeOSSettings, OutcomeController } from "../src/index.js";
class Client implements BridgeClient { calls=0; async start(_s:LifeOSSettings):Promise<HandshakeResult>{throw new Error("unused");} async call<T>():Promise<T>{this.calls++;return {reference:{path:"plans/p.md"}} as T;} onNotification():()=>void{return()=>{};} async stop():Promise<void>{} }
test("outcome controller supports common two-click completion", async()=>{const client=new Client();const c=new OutcomeController(client);await c.submit({idempotency_key:"e",plan_path:"plans/p.md",task_id:"t",outcome:"done",day:"2026-07-16",expected_hash:"h"});assert.equal(client.calls,1);});
test("outcome validation keeps states distinct",()=>{const c=new OutcomeController(new Client());assert.equal(c.validate({idempotency_key:"e",plan_path:"p",task_id:"t",outcome:"deferred",day:"2026-07-16",expected_hash:"h",deferred_until:"bad"}).length,1);});
