import { BridgeClient } from "./protocol.js";
export interface ScheduleConfig{enabled:boolean;timezone:string;morning:string;evening:string;weekly_day:number;weekly:string;quiet_start:string;quiet_end:string;privacy:"generic"|"titles";grace_hours:number;}
export class SchedulerController{
  constructor(private readonly client:BridgeClient){}
  getConfig():Promise<ScheduleConfig>{return this.client.call("scheduler.config.get",{});}
  saveConfig(config:ScheduleConfig):Promise<ScheduleConfig>{return this.client.call("scheduler.config.set",config as unknown as Record<string,unknown>);}
  status():Promise<{installed:boolean;descriptors:string[]}>{return this.client.call("scheduler.service.status",{});}
  install(command:string[]):Promise<unknown>{return this.client.call("scheduler.service.install",{command});}
  uninstall():Promise<unknown>{return this.client.call("scheduler.service.uninstall",{});}
}
