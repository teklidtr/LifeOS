import { BridgeClient } from "./protocol.js";
export type StudySessionState="active"|"paused"|"finished"|"abandoned";
export interface StudySession{session_id:string;state:StudySessionState;day:string;topic?:string;budget_minutes:number;card_ids:string[];card_paths:string[];actual_minutes?:number;source_changes:string[];}
export class StudySessionController{
  constructor(private readonly client:BridgeClient){}
  plan(day:string,minutes:number,topic?:string):Promise<unknown>{return this.client.call("study.plan",{day,minutes,topic});}
  start(day:string,minutes:number,topic?:string):Promise<StudySession>{return this.client.call("study.session.start",{day,minutes,topic});}
  transition(sessionId:string,action:"pause"|"resume"|"finish"|"abandon",actualMinutes?:number):Promise<StudySession>{return this.client.call("study.session.transition",{session_id:sessionId,action,actual_minutes:actualMinutes});}
  openSessions():Promise<StudySession[]>{return this.client.call("study.session.open",{});}
  sourceLink(session:StudySession,index:number):string|undefined{return session.card_paths[index];}
}
