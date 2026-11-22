/* Build-time limits for the bundled PJSIP. Applied by scripts/build_pjsip.sh. */
#define PJSUA_MAX_CALLS          64     /* upstream default: 4  */
#define PJSUA_MAX_PLAYERS        64     /* upstream default: 32 */
#define PJSUA_MAX_RECORDERS      64     /* upstream default: 32 */
#define PJ_IOQUEUE_MAX_HANDLES   512    /* each call opens RTP + RTCP sockets */
