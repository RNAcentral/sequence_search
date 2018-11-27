import React from 'react';
import {Route, Link, Redirect, Switch} from 'react-router-dom';
import 'ebi-framework/js/script.js';
import 'foundation-sites/dist/js/foundation.js';
import 'ebi-framework/js/foundationExtendEBI.js';
import 'jquery/dist/jquery.js';

// import 'foundation-sites/dist/css/foundation.css';  // clash with ebi-framework1.3: header 'display: block/flexbox'
import 'ebi-framework/css/ebi-global.css';
import 'ebi-framework/css/theme-light.css';
import 'EBI-Icon-fonts/fonts.css';
import 'animate.css/animate.min.css';
import 'styles/style.scss';

import PropsRoute from 'components/PropsRoute.jsx'
import Header from 'components/Header/index.jsx';
import InnerHeader from 'components/InnerHeader/index.jsx';
import Footer from 'components/Footer/index.jsx';

import Search from 'pages/Search/index.jsx';
import Job from 'pages/Job/index.jsx';
import Result from 'pages/Result/index.jsx';
import Documentation from 'pages/Documentation/index.jsx';
import About from 'pages/About/index.jsx';
import Error from 'pages/Error/index.jsx';


class Layout extends React.Component {
  constructor(props) {
    super(props);

    this.state = {
    };
  }

  render() {
    return [
        <div id="skip-to" key="skip-to">
          <ul>
            <li><a href="#content">Skip to main content</a></li>
            <li><a href="#local-nav">Skip to local navigation</a></li>
            <li><a href="#global-nav">Skip to EBI global navigation menu</a></li>
            <li><a href="#global-nav-expanded">Skip to expanded EBI global navigation menu (includes all sub-sections)</a>
            </li>
          </ul>
        </div>,

        <Header key="Header" />,

        <div id="content" key="content">
          <div data-sticky-container>
            <InnerHeader key="InnerHeader" />
          </div>

          <section id="main-content-area" className="row" role="main">

            <div className="columns margin-top-large margin-bottom-large">
              <section>
                <Switch>
                  <PropsRoute exact path="/search" component={Search} />
                  <PropsRoute path="/job/:jobId" component={Job} />
                  <PropsRoute path="/result/:resultId" component={Result} />
                  <PropsRoute path="/documentation" component={Documentation} />
                  <PropsRoute path="/about" component={About} />
                  <PropsRoute path="/error" component={Error} />
                  <Redirect to="/search" />
                </Switch>
              </section>
            </div>

          </section>
        </div>,

        <Footer key="Footer" />
    ]
  }

  componentDidMount() {
    $(document).foundation();
    $(document).foundationExtendEBI();
  }

}

export default Layout;
