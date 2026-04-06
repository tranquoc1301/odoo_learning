import {Component, markup, useState} from "@odoo/owl";
import {Counter} from "./components/counter/counter";
import {Card} from "./components/card/card";

export class Playground extends Component {
    static template = "awesome_owl.playground";
    static components = {Counter, Card};

    setup() {
        this.html = markup("<h1>Hi</h1>");
        this.sum = useState({value: 2})
    }

    incrementSum() {
        this.sum.value++;
    }

}
