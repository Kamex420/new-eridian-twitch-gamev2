"""Incident aftermath supplements existing rewards and preserves history."""
def incident_effect(shared,competency,result):
    success=result=="success"
    magnitude=2 if result=="partial" else 4
    shared.mood=max(0,min(100,shared.mood+(4 if success else -magnitude)))
    field={"environmental":"water","infrastructure":"infrastructure","fabrication":"components","logistics":"cargo"}.get(competency)
    if field:setattr(shared,field,max(0,getattr(shared,field)+(magnitude if success else -magnitude)))
