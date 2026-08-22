import { BridgeClient } from "./protocol.js";
export type ProposalAction="submit"|"approve"|"apply"|"reject";
export interface ProposalInspection{proposal_id:string;status:string;title:string;description:string;body:string;review_digest:string;operations:Array<Record<string,unknown>>;related_sources:string[];findings:string[];}
export interface ConfirmationChallenge{token:string;proposal_id:string;action:ProposalAction;review_digest:string;expires_at:string;}
export class ProposalController{
  inspected?:ProposalInspection;
  constructor(private readonly client:BridgeClient,private readonly confirm:(challenge:ConfirmationChallenge,inspection:ProposalInspection)=>Promise<boolean>){}
  list():Promise<ProposalInspection[]>{return this.client.call("proposal.list",{});}
  async inspect(id:string):Promise<ProposalInspection>{const inspection=await this.client.call<ProposalInspection>("proposal.inspect",{proposal_id:id});this.inspected=inspection;return inspection;}
  async execute(id:string,action:ProposalAction,reason?:string):Promise<unknown>{const inspection=await this.inspect(id);const challenge=await this.client.call<ConfirmationChallenge>("proposal.prepare",{proposal_id:id,action});if(!(await this.confirm(challenge,inspection)))throw new Error("Confirmation cancelled.");const latest=await this.inspect(id);if(latest.review_digest!==challenge.review_digest)throw new Error("Proposal changed after review.");return this.client.call("proposal.execute",{proposal_id:id,action,token:challenge.token,reason});}
}
export class SystemController{constructor(private readonly client:BridgeClient){} status():Promise<unknown>{return this.client.call("system.status",{});}}
