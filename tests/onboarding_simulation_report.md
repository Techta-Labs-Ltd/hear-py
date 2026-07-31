# Onboarding Simulation Report

Live simulation of the onboarding checklist through the real skill stack (AsyncSkill + middleware + registry + memory persistence), with only the resolver Lambda and the Hear API mocked.

## Status counts

| Status | Count |
| --- | --- |
| OK | 51 |
| GAP | 0 |
| FAIL | 3 |

## Scenarios

### S1 permission ask + consent card

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 2 | AMAZON.YesIntent | ask_permission | ask_permission | OK | I've sent a card to your Alexa app — open it and tap to share your location. If you'd rather not, you can just tell me your town and I'll take it from there. |  |
| 3 | Connections.Response | ask_permission | await_location_confirm | OK | Bear with me a second, just finding you on the map... I think you're in Swindon — is that right? |  |
| 4 | AMAZON.YesIntent | await_location_confirm | - | OK | Thanks. I've set your location to Swindon. You can ask for local news or sport, play from a talking newspaper, or say what's trending. What would you like to hear? Would you like to hear the latest from Swindon? |  |
| 5 | AMAZON.YesIntent | - | - | OK | I couldn't find anything available from Swindon right now. |  |
| 6 | LaunchRequest | - | - | FAIL | Hello, welcome to Hear. You can say what's trending, play news, or play from a creator. What would you like? |  |
### S2 manual town happy path

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 2 | AMAZON.NoIntent | ask_permission | ask_town | OK | No worries. Which town or city are you in? |  |
| 3 | TownCaptureIntent | ask_town | await_location_confirm | OK | Did you say Swindon? |  |
| 4 | AMAZON.YesIntent | await_location_confirm | - | OK | Thanks. I've set your location to Swindon. You can ask for local news or sport, play from a talking newspaper, or say what's trending. What would you like to hear? Would you like to hear the latest from Swindon? |  |
| 5 | PlayContentIntent | - | - | OK | Did you want me to play news? |  |
| 6 | LaunchRequest | - | - | FAIL | Hello, welcome to Hear. You can say what's trending, play news, or play from a creator. What would you like? |  |
### S3 ambiguous town

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 2 | AMAZON.NoIntent | ask_permission | ask_town | OK | No worries. Which town or city are you in? |  |
| 3 | TownCaptureIntent | ask_town | ask_town | OK | Did you mean Wakefield or Walsall? Please say the full town name. |  |
| 4 | TownCaptureIntent | ask_town | await_location_confirm | OK | Did you say Wakefield? |  |
| 5 | AMAZON.YesIntent | await_location_confirm | - | OK | Thanks. I've set your location to Wakefield. You can ask for local news or sport, play from a talking newspaper, or say what's trending. What would you like to hear? Would you like to hear the latest from Wakefield? |  |
### S4 town attempts cap then skip

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 2 | AMAZON.NoIntent | ask_permission | ask_town | OK | No worries. Which town or city are you in? |  |
| 3 | TownCaptureIntent | ask_town | ask_town | OK | Just the town name please — like London or Manchester. Or say skip if you'd rather not. |  |
| 4 | TownCaptureIntent | ask_town | ask_town | OK | Just the town name please — like London or Manchester. Or say skip if you'd rather not. |  |
| 5 | TownCaptureIntent | ask_town | ask_town | OK | Just the town name please — like London or Manchester. Or say skip if you'd rather not. |  |
| 6 | TownCaptureIntent | ask_town | - | OK | Okay. What would you like to listen to? |  |
| 7 | PlayContentIntent | - | - | OK | Did you want me to play news? |  |
### S5 community request without location

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | BrowseContentIntent | - | confirm_town_for_community | OK | I'll need your town to find local content. Would you like to set that up? |  |
| 2 | TownCaptureIntent | confirm_town_for_community | await_location_confirm | OK | Did you say Swindon? |  |
| 3 | AMAZON.YesIntent | await_location_confirm | - | OK | Thanks. I've set your location to Swindon. You can ask for local news or sport, play from a talking newspaper, or say what's trending. What would you like to hear? Would you like to hear the latest from Swindon? |  |
| 4 | PlayContentIntent | - | - | OK | Did you want me to play tracks near you? |  |
| 5 | AMAZON.YesIntent | - | - | OK | I couldn't find anything for tracks near you right now. What would you like to try instead? |  |
### S6 returning user named

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | - | OK | Welcome back to Hear, John. You can say what's trending, play news, or play from a talking newspaper. What would you like? |  |
### S7 set location

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SetLocationIntent | - | await_location_confirm | OK | Did you say Manchester? |  |
| 2 | AMAZON.YesIntent | await_location_confirm | - | OK | Thanks. I've set your location to Manchester. You can ask for local news or sport, play from a talking newspaper, or say what's trending. What would you like to hear? Would you like to hear the latest from Manchester? |  |
### S8 consent card denied

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 2 | AMAZON.YesIntent | ask_permission | ask_permission | OK | I've sent a card to your Alexa app — open it and tap to share your location. If you'd rather not, you can just tell me your town and I'll take it from there. |  |
| 3 | Connections.Response | ask_permission | ask_town | OK | No worries. Which town or city are you in? |  |
### S9 relaunch with granted scopes

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | await_location_confirm | OK | Bear with me a second, just finding you on the map... I think you're in Swindon — is that right? |  |
| 2 | AMAZON.NoIntent | await_location_confirm | - | OK | No problem. Which city should I set instead? |  |
| 3 | TownCaptureIntent | - | - | FAIL | Just say yes to share your location, or no to tell me your town instead. |  |
### S10 off-script replies stay in stage

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 2 | AMAZON.NoIntent | ask_permission | ask_town | OK | No worries. Which town or city are you in? |  |
| 3 | AMAZON.FallbackIntent | ask_town | ask_town | OK | Just the town name please — like London or Manchester. Or say skip if you'd rather not. |  |
| 4 | WhatsTrendingIntent | ask_town | ask_town | OK | Just the town name please — like London or Manchester. Or say skip if you'd rather not. |  |
| 5 | TownCaptureIntent | ask_town | await_location_confirm | OK | Did you say Burnley? |  |
| 6 | PlayContentIntent | await_location_confirm | await_location_confirm | OK | Did you say Burnley? |  |
| 7 | LaunchRequest | await_location_confirm | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 8 | AMAZON.YesIntent | ask_permission | ask_permission | OK | I've sent a card to your Alexa app — open it and tap to share your location. If you'd rather not, you can just tell me your town and I'll take it from there. |  |
### S11 content or skip classified at town capture

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 2 | AMAZON.NoIntent | ask_permission | ask_town | OK | No worries. Which town or city are you in? |  |
| 3 | TownCaptureIntent | ask_town | ask_town | OK | Happy to play that for you. First, which town or city are you in? Or say skip. |  |
| 4 | TownCaptureIntent | ask_town | - | OK | Okay. What would you like to listen to? |  |
### S12 returning user dangling stage is redirected

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | AMAZON.FallbackIntent | ask_town | ask_town | OK | Just the town name please — like London or Manchester. Or say skip if you'd rather not. |  |
### S13 relaunch mid onboarding resets stage

| Step | Intent | Stage in | Stage out | Status | Speech | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LaunchRequest | - | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |
| 2 | AMAZON.NoIntent | ask_permission | ask_town | OK | No worries. Which town or city are you in? |  |
| 3 | LaunchRequest | ask_town | ask_permission | OK | Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright? |  |

## GAPS

No gaps reproduced in this run.

Real-device/live-skill testing is not possible on this machine; this simulation is the verification boundary.
