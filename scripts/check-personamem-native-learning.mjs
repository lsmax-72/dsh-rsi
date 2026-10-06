// Offline gate replay. Input contains native logs and counters, never scorer answers.
import {decideClosedNativeLearning} from './personamem-native-learning-policy.mjs';
let input='';for await(const chunk of process.stdin)input+=chunk;
console.log(JSON.stringify(decideClosedNativeLearning(JSON.parse(input))));
