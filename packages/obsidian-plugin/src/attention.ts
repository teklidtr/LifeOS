import { BridgeClient } from "./protocol.js";
import { OutcomeController, OutcomeDraft } from "./outcomes.js";
export interface AttentionItem { item_id:string; kind:string; severity:"info"|"attention"|"important"; title:string; explanation:string; first_seen:string; evidence:Array<{path:string;detail:string}>; actions:Array<{action:string;label:string}>; }
export interface AttentionResult { as_of:string; items:AttentionItem[]; diagnostics:string[]; }
export class AttentionController {
  constructor(private readonly client:BridgeClient, private readonly outcomes:OutcomeController) {}
  evaluate(asOf:string):Promise<AttentionResult>{return this.client.call("attention.evaluate",{as_of:asOf});}
  snooze(itemId:string,until:string):Promise<unknown>{return this.client.call("attention.preference",{item_id:itemId,snooze_until:until});}
  dismiss(itemId:string):Promise<unknown>{return this.client.call("attention.preference",{item_id:itemId,dismiss:true});}
  reconcile(draft:OutcomeDraft):Promise<unknown>{return this.outcomes.submit(draft);}
}
