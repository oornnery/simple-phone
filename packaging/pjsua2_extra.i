// simple-phone additions to the PJSUA2 binding. scripts/build_pjsip.sh
// appends this file to pjsua2.i before it runs SWIG.

%inline %{
// Header names in compact form (i:, f:, t:, v:...) in every message PJSIP
// sends. pjsip_cfg() is process-wide: it applies to every account.
void setCompactForm(bool enabled)
{
    pjsip_cfg()->endpt.use_compact_form = enabled ? PJ_TRUE : PJ_FALSE;
}

bool getCompactForm()
{
    return pjsip_cfg()->endpt.use_compact_form == PJ_TRUE;
}
%}
