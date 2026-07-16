import { BridgeClient } from "./protocol.js";
export type ReviewKind="morning"|"evening"|"weekly";
export interface ReviewItem{item_id:string;title:string;detail:string;source_path?:string;action?:string;}
export interface ReviewSection{section_id:string;title:string;optional:boolean;state:"ready"|"empty"|"unavailable";items:ReviewItem[];diagnostic?:string;}
export interface ReviewWorkflow{review_id:string;kind:ReviewKind;day:string;range_start:string;range_end:string;sections:ReviewSection[];progress:{completed_sections:string[];skipped_sections:string[];current_section?:string};facts_markdown:string;}
export class ReviewWizardController{
  workflow?:ReviewWorkflow;
  constructor(private readonly client:BridgeClient,private readonly openPath:(path:string)=>void){}
  async start(kind:ReviewKind,day:string):Promise<ReviewWorkflow>{this.workflow=await this.client.call("review.build",{kind,day});return this.workflow;}
  async mark(sectionId:string,state:"complete"|"skip"):Promise<void>{if(!this.workflow)throw new Error("Review is not loaded.");const completed=new Set(this.workflow.progress.completed_sections);const skipped=new Set(this.workflow.progress.skipped_sections);if(state==="complete"){completed.add(sectionId);skipped.delete(sectionId);}else{skipped.add(sectionId);completed.delete(sectionId);}this.workflow.progress=await this.client.call("review.progress",{review_id:this.workflow.review_id,completed_sections:[...completed],skipped_sections:[...skipped],current_section:sectionId});}
  async save(idempotencyKey:string,expectedHash?:string):Promise<{reference:{path:string}}>{if(!this.workflow)throw new Error("Review is not loaded.");const result=await this.client.call<{reference:{path:string}}>("review.save",{kind:this.workflow.kind,day:this.workflow.day,idempotency_key:idempotencyKey,expected_hash:expectedHash});this.openPath(result.reference.path);return result;}
  open(item:ReviewItem):void{if(item.source_path)this.openPath(item.source_path);}
}
